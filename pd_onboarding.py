"""Separate driver connection applications. Decisions and records stay in the admin cabinet."""
import json,re,io,warnings,hashlib
from PIL import Image,ImageOps,UnidentifiedImageError
from flask import Response
SIDES=("license_front","license_back","registration_front","registration_back","ltsa","activity","insurance","portrait","car_front","car_rear","car_interior")
ACTIVE_SIDES=("license_front","license_back","car_front","car_rear","car_interior")
MAX_PHOTO=10*1024*1024
from flask import request,jsonify
import pd_languages

def ensure_tables(core):
    with core.db(core.USERS_DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pd_driver_applications (
            telegram_id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
            city TEXT NOT NULL, vehicle TEXT NOT NULL, vehicle_year INTEGER NOT NULL,
            plate TEXT NOT NULL, seats INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pd_driver_application_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,old_status TEXT NOT NULL,new_status TEXT NOT NULL,
            decided_at TEXT NOT NULL)''')

def read_photos():
    photos={}
    for side in SIDES:
        f=request.files.get(side)
        if not f:continue
        if side not in ACTIVE_SIDES:raise ValueError("Загружаются водительские права и три фотографии автомобиля")
        data=f.read(MAX_PHOTO+1)
        if len(data)>MAX_PHOTO:raise ValueError('Фото слишком большое: максимум 10 МБ')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                im=Image.open(io.BytesIO(data))
                if im.format not in ('JPEG','PNG','WEBP') or getattr(im,'n_frames',1)!=1:raise ValueError('Выберите фото в формате JPEG, PNG или WebP')
                if im.width*im.height>24000000 or min(im.size)<800 or max(im.size)<1200:raise ValueError('Нужно чёткое фото: минимум 1200 × 800 пикселей')
                im.load();im=ImageOps.exif_transpose(im).convert('RGB')
                im.thumbnail((3200,3200));out=io.BytesIO();im.save(out,format='JPEG',quality=94)
                photos[side]=out.getvalue()
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise ValueError('Не удалось прочитать фото. Выберите другой снимок')
    return photos

def register(app,core,auth):
    ensure_tables(core)
    app.config['MAX_CONTENT_LENGTH']=82*1024*1024
    @app.errorhandler(413)
    def pd_documents_too_large(exc):return jsonify(error='Файлы слишком большие. Максимум 10 МБ на фото'),413
    with core.db(core.USERS_DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS pd_driver_documents (
          telegram_id INTEGER NOT NULL,side TEXT NOT NULL,image BLOB NOT NULL,
          updated_at TEXT NOT NULL,PRIMARY KEY(telegram_id,side))""")
    def document_sides(uid):
        with core.db(core.USERS_DB) as c:
            return [r['side'] for r in c.execute('SELECT side FROM pd_driver_documents WHERE telegram_id=?',(uid,))]
    @app.get('/api/driver/documents/<int:applicant>/<side>')
    def pd_driver_document(applicant,side):
        uid,_=auth()
        if uid!=applicant and not core.is_admin(uid):raise PermissionError('Нет доступа')
        if side not in SIDES:return jsonify(error='Фото не найдено'),404
        with core.db(core.USERS_DB) as c:
            row=c.execute('SELECT image FROM pd_driver_documents WHERE telegram_id=? AND side=?',(applicant,side)).fetchone()
        if not row:return jsonify(error='Фото не найдено'),404
        return Response(bytes(row['image']),mimetype='image/jpeg',headers={
          'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
          'Content-Disposition':'inline; filename="document.jpg"','Referrer-Policy':'no-referrer'})
    def own(uid):
        with core.db(core.USERS_DB) as c:
            row=c.execute('''SELECT name,phone,city,vehicle,vehicle_year,plate,seats,
                 status, created_at AS submitted_at FROM pd_driver_applications WHERE telegram_id=?''',(uid,)).fetchone()
        return dict(submitted=True,document_sides=document_sides(uid),**dict(row)) if row else None
    previous_me=app.view_functions['me']
    def me_with_registration():
        uid,_=auth();data=previous_me().get_json();data['driver_application']=own(uid)
        return jsonify(data)
    app.view_functions['me']=me_with_registration

    @app.post('/api/driver/application')
    def pd_driver_apply():
        uid,_=auth()
        try:d=json.loads(request.form.get('application','null')) if request.mimetype=='multipart/form-data' else request.get_json(silent=True)
        except (ValueError,TypeError):raise ValueError('Проверьте данные заявки водителя')
        if not isinstance(d,dict):raise ValueError('Проверьте данные заявки водителя')
        out={}
        for key,limit in [('name',80),('phone',40),('city',120),('vehicle',120),('plate',16)]:
            value=d.get(key)
            if not isinstance(value,str):raise ValueError('Заполните все поля регистрации водителя')
            out[key]=' '.join(value.split())
            if not 2<=len(out[key])<=limit:raise ValueError('Заполните все поля регистрации водителя')
        phone=core.clean_phone(out['phone'])
        if not phone:raise ValueError('Неверный номер телефона')
        year=d.get('vehicle_year');seats=d.get('seats')
        if type(year) is not int or not 1980<=year<=core.now().year+1:raise ValueError('Проверьте год выпуска автомобиля')
        if type(seats) is not int or not 1<=seats<=8:raise ValueError('Укажите от 1 до 8 пассажирских мест')
        plate=out['plate'].upper()
        if not all(ch.isalnum() or ch in ' -' for ch in plate):raise ValueError('Проверьте номер автомобиля')
        photos=read_photos()
        core.initialize()
        now=core.now().isoformat()
        with core.db(core.USERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            stored={r['side'] for r in c.execute('SELECT side FROM pd_driver_documents WHERE telegram_id=?',(uid,))}
            if set(ACTIVE_SIDES)-stored-set(photos):raise ValueError('Добавьте все обязательные фотографии документов')
            car_rows={x['side']:bytes(x['image']) for x in c.execute("SELECT side,image FROM pd_driver_documents WHERE telegram_id=? AND side IN ('car_front','car_rear','car_interior')",(uid,))}
            car_rows.update({k:v for k,v in photos.items() if k.startswith('car_')})
            if len({hashlib.sha256(v).digest() for v in car_rows.values()})!=3:raise ValueError('Добавьте три разных фото автомобиля: спереди, сзади и салон')
            for side,image in photos.items():
                c.execute('INSERT INTO pd_driver_documents(telegram_id,side,image,updated_at) VALUES(?,?,?,?) ON CONFLICT(telegram_id,side) DO UPDATE SET image=excluded.image,updated_at=excluded.updated_at',(uid,side,image,now))
            c.execute('''INSERT INTO pd_driver_applications
              (telegram_id,name,phone,city,vehicle,vehicle_year,plate,seats,status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,'pending',?,?) ON CONFLICT(telegram_id) DO UPDATE SET
              name=excluded.name,phone=excluded.phone,city=excluded.city,vehicle=excluded.vehicle,
              vehicle_year=excluded.vehicle_year,plate=excluded.plate,seats=excluded.seats,
              status='pending',updated_at=excluded.updated_at''',
              (uid,out['name'],phone,out['city'],out['vehicle'],year,plate,seats,now,now))
        return jsonify(ok=True,submitted=True)

    @app.get('/api/admin/driver-applications')
    def pd_driver_applications():
        uid,_=auth()
        if not core.is_admin(uid):raise PermissionError('Нет доступа')
        with core.db(core.USERS_DB) as c:
            rows=c.execute('SELECT * FROM pd_driver_applications ORDER BY updated_at DESC LIMIT 200').fetchall()
        return jsonify(applications=[dict(**dict(r),document_sides=document_sides(r["telegram_id"])) for r in rows])

    @app.post('/api/admin/driver-applications/<int:applicant>/decision')
    def pd_driver_decide(applicant):
        uid,_=auth()
        if not core.is_admin(uid):raise PermissionError('Нет доступа')
        d=request.get_json(silent=True);target=d.get('status') if isinstance(d,dict) else None
        if target not in ('pending','approved','rejected'):raise ValueError('Некорректный статус заявки')
        with core.db(core.USERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT status FROM pd_driver_applications WHERE telegram_id=?',(applicant,)).fetchone()
            if not r:return jsonify(error='Заявка не найдена'),404
            if target=='approved' and r['status']!='approved':
                stored={x['side'] for x in c.execute('SELECT side FROM pd_driver_documents WHERE telegram_id=?',(applicant,))}
                if set(ACTIVE_SIDES)-stored:
                    raise ValueError('Для одобрения нужны обе стороны прав и три фотографии автомобиля')
            if r['status']!=target:
                now=core.now().isoformat()
                c.execute('UPDATE pd_driver_applications SET status=?,updated_at=? WHERE telegram_id=?',(target,now,applicant))
                c.execute('INSERT INTO pd_driver_application_decisions(telegram_id,admin_id,old_status,new_status,decided_at) VALUES(?,?,?,?,?)',(applicant,uid,r['status'],target,now))
        # Reviewing an application never grants administrator access or exposes customer orders.
        return jsonify(ok=True)

    @app.get('/driver-privacy')
    def pd_driver_privacy():
        lang=pd_languages.language()
        return pd_languages.response_for(app.jinja_env.get_template('driver_privacy_'+lang+'.html').render(),lang)
