"""Separate driver connection applications. Decisions and records stay in the admin cabinet."""
import json,re,io,warnings,hashlib
from PIL import Image,ImageOps,UnidentifiedImageError
from flask import Response
SIDES=("license_front","license_back","registration_front","registration_back","ltsa","activity","insurance","portrait","car_front","car_rear","car_interior")
ACTIVE_SIDES=("license_front","license_back","portrait","car_front","car_rear","car_interior")
DRIVER_TERMS_VERSION="pd-driver-terms-v1"
PROFILE_PHOTOS=("portrait","car_front")
MAX_PHOTO=10*1024*1024
from flask import request,jsonify
import pd_languages

def ensure_tables(core):
    with core.db(core.USERS_DB) as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('''CREATE TABLE IF NOT EXISTS pd_driver_applications (
            telegram_id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
            city TEXT NOT NULL, vehicle TEXT NOT NULL, vehicle_year INTEGER NOT NULL,
            plate TEXT NOT NULL, seats INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            terms_version TEXT, terms_accepted_at TEXT)''')
        columns={r['name'] for r in c.execute('PRAGMA table_info(pd_driver_applications)')}
        for column in ('terms_version','terms_accepted_at'):
            if column not in columns:c.execute(f'ALTER TABLE pd_driver_applications ADD COLUMN {column} TEXT')
        c.execute('''CREATE TABLE IF NOT EXISTS pd_driver_application_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,old_status TEXT NOT NULL,new_status TEXT NOT NULL,
            decided_at TEXT NOT NULL)''')

def read_photos():
    photos={}
    for side in SIDES:
        f=request.files.get(side)
        if not f:continue
        if side not in ACTIVE_SIDES:raise ValueError("Загружаются обе стороны прав, портрет и три фотографии автомобиля")
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
    def photo_response(row):
        if not row:return jsonify(error='Фото не найдено'),404
        return Response(bytes(row['image']),mimetype='image/jpeg',headers={
          'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
          'Content-Disposition':'inline; filename="document.jpg"','Referrer-Policy':'no-referrer'})

    @app.get('/api/driver/documents/<int:applicant>/<side>')
    def pd_driver_document(applicant,side):
        uid,_=auth()
        if uid!=applicant and not core.is_admin(uid):raise PermissionError('Нет доступа')
        if side not in SIDES:return jsonify(error='Фото не найдено'),404
        with core.db(core.USERS_DB) as c:
            row=c.execute('SELECT image FROM pd_driver_documents WHERE telegram_id=? AND side=?',(applicant,side)).fetchone()
        return photo_response(row)

    def assigned_pilot(uid,order_id):
        with core.db(core.ORDERS_DB) as c:
            return c.execute("""SELECT o.id,a.pilot_id FROM orders o
                 LEFT JOIN pd_pilot_assignments a ON a.order_id=o.id
                 WHERE o.telegram_id=? AND o.status<>'Отменена'
                   AND ((? IS NOT NULL AND o.id=?) OR (? IS NULL
                        AND o.status IN ('Новая','Подтверждена','В пути')))
                 ORDER BY o.id DESC LIMIT 1""",(uid,order_id,order_id,order_id)).fetchone()

    def approved_profile(pilot_id):
        with core.db(core.USERS_DB) as c:
            return c.execute("""SELECT name,vehicle,vehicle_year,plate,terms_version,terms_accepted_at
                FROM pd_driver_applications WHERE telegram_id=? AND status='approved'""",(pilot_id,)).fetchone()

    @app.get('/api/orders/pilot-profile')
    @app.get('/api/orders/<int:order_id>/pilot-profile')
    def passenger_pilot_profile(order_id=None):
        uid,_=auth()
        assignment=assigned_pilot(uid,order_id)
        if order_id is not None and not assignment:return jsonify(error='Заказ не найден'),404
        pilot=approved_profile(assignment['pilot_id']) if assignment else None
        if not pilot:return jsonify(pilot=None)
        profile={key:pilot[key] for key in ('name','vehicle','vehicle_year','plate')}
        profile['photos']={}
        if pilot['terms_version']==DRIVER_TERMS_VERSION and pilot['terms_accepted_at']:
            profile['photos']={side:f"/api/orders/{assignment['id']}/pilot-profile/photos/{side}"
                               for side in document_sides(assignment['pilot_id']) if side in PROFILE_PHOTOS}
        return jsonify(pilot=profile)

    @app.get('/api/orders/<int:order_id>/pilot-profile/photos/<side>')
    def passenger_pilot_photo(order_id,side):
        uid,_=auth()
        if side not in PROFILE_PHOTOS:return photo_response(None)
        assignment=assigned_pilot(uid,order_id)
        if not assignment:return photo_response(None)
        with core.db(core.USERS_DB) as c:
            row=c.execute("""SELECT d.image FROM pd_driver_documents d
                JOIN pd_driver_applications a ON a.telegram_id=d.telegram_id
                WHERE d.telegram_id=? AND d.side=? AND a.status='approved'
                 AND a.terms_version=? AND a.terms_accepted_at IS NOT NULL""",
                (assignment['pilot_id'],side,DRIVER_TERMS_VERSION)).fetchone()
        return photo_response(row)

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
        if d.get('terms_accepted') is not True or d.get('terms_version')!=DRIVER_TERMS_VERSION:
            raise ValueError('Подтвердите актуальные условия регистрации водителя')
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
              (telegram_id,name,phone,city,vehicle,vehicle_year,plate,seats,status,created_at,updated_at,terms_version,terms_accepted_at)
              VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
              name=excluded.name,phone=excluded.phone,city=excluded.city,vehicle=excluded.vehicle,
              vehicle_year=excluded.vehicle_year,plate=excluded.plate,seats=excluded.seats,
              status='pending',updated_at=excluded.updated_at,terms_version=excluded.terms_version,
              terms_accepted_at=excluded.terms_accepted_at''',
              (uid,out['name'],phone,out['city'],out['vehicle'],year,plate,seats,now,now,DRIVER_TERMS_VERSION,now))
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
            r=c.execute('SELECT status,updated_at,terms_version,terms_accepted_at FROM pd_driver_applications WHERE telegram_id=?',(applicant,)).fetchone()
            if not r:return jsonify(error='Заявка не найдена'),404
            if 'updated_at' in d and d['updated_at']!=r['updated_at']:
                return jsonify(error='Заявка изменилась. Проверьте обновлённые данные'),409
            if target=='approved' and r['status']!='approved':
                if r['terms_version']!=DRIVER_TERMS_VERSION or not r['terms_accepted_at']:
                    raise ValueError('Водитель должен подтвердить условия регистрации')
                stored={x['side'] for x in c.execute('SELECT side FROM pd_driver_documents WHERE telegram_id=?',(applicant,))}
                if set(ACTIVE_SIDES)-stored:
                    raise ValueError('Для активации нужны обе стороны прав, портрет и три фотографии автомобиля')
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
