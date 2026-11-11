"""Private staged pilot photos; only dispatcher approval changes the active image."""
from pathlib import Path
from flask import request, jsonify, Response

KINDS = ('profile','license_front','license_back','registration_front','registration_back',
         'ltsa','activity','insurance','portrait','car_front','car_rear','car_interior')

def register(app, core, auth, photo_bytes, clock):
    with core.db(core.USERS_DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pd_photo_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
            kind TEXT NOT NULL, jpeg BLOB NOT NULL, status TEXT NOT NULL,
            created_at INTEGER NOT NULL, reviewer_id INTEGER, reviewed_at INTEGER,
            reason TEXT NOT NULL DEFAULT '')''')
        c.execute('CREATE INDEX IF NOT EXISTS pd_photo_review_owner ON pd_photo_reviews(owner_id,kind,id)')
    def application(c, uid):
        return c.execute('SELECT * FROM pd_driver_applications WHERE telegram_id=?',(uid,)).fetchone()
    def upload(uid, kind):
        if kind not in KINDS:raise ValueError('Недопустимый тип фотографии')
        with core.db(core.USERS_DB) as c:
            pilot=application(c,uid)
        if not pilot and not core.is_admin(uid):raise PermissionError('Фото загружает пилот или диспетчер')
        if kind!='profile':
            if not pilot:raise ValueError('Сначала заполните анкету пилота')
            import pd_onboarding
            allowed=pd_onboarding.SIDES if pilot['stage']==2 or pilot['status']=='stage2' else pd_onboarding.ACTIVE_SIDES
            if kind not in allowed:raise ValueError('Этот документ доступен на втором этапе регистрации')
            if set(request.files)!={kind}:raise ValueError('Выберите одну фотографию')
            photos=pd_onboarding.read_photos(allowed)
            if kind not in photos:raise ValueError('Выберите фотографию')
            jpeg=photos[kind]
        else:
            if set(request.files)!={'photo'}:raise ValueError('Выберите одну фотографию')
            jpeg=photo_bytes(request.files['photo'].stream.read(5*1024*1024+1))
        with core.db(core.USERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute("UPDATE pd_photo_reviews SET status='superseded' WHERE owner_id=? AND kind=? AND status='pending'",(uid,kind))
            row=c.execute("INSERT INTO pd_photo_reviews(owner_id,kind,jpeg,status,created_at) VALUES(?,?,?,'pending',?)",(uid,kind,jpeg,int(clock())))
            rid=row.lastrowid
        return jsonify(ok=True,status='pending',review_id=rid)

    # Keep existing clients compatible, but remove their direct publication path.
    original_avatar=app.view_functions['pd_profile_avatar_v6']
    def moderated_avatar():
        uid,_=auth()
        with core.db(core.USERS_DB) as c:pilot=application(c,uid)
        if request.method=='POST' and (pilot or core.is_admin(uid)):
            return upload(uid,'profile')
        if request.method=='DELETE':
            with core.db(core.USERS_DB) as c:
                c.execute("UPDATE pd_photo_reviews SET status='withdrawn' WHERE owner_id=? AND kind='profile' AND status='pending'",(uid,))
        return original_avatar()
    app.view_functions['pd_profile_avatar_v6']=moderated_avatar

    @app.before_request
    def protect_approved_photo_replacement():
        if request.path=='/api/driver/application' and request.method=='POST' and request.files:
            uid,_=auth()
            with core.db(core.USERS_DB) as c:pilot=application(c,uid)
            if pilot and pilot['status']=='approved':
                raise ValueError('Замените фото через «Документы и фото»: снимок сначала проверит диспетчер')

    @app.after_request
    def private_reviews(response):
        if request.path=='/' and response.status_code==200 and response.mimetype=='text/html':
            html=response.get_data(as_text=True)
            if '/assets/pd-photo-review.js' not in html:
                response.set_data(html.replace('</body>','<script src="/assets/pd-photo-review.js?v=20261111"></script></body>'))
        if request.path.startswith('/api/photo-review'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['Vary']='X-Telegram-Init-Data'
            response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/assets/pd-photo-review.js')
    def photo_review_script():
        return Response(Path(__file__).with_suffix('.js').read_text(),mimetype='application/javascript',headers={'Cache-Control':'no-cache'})

    @app.post('/api/photo-review/upload/<kind>')
    def photo_review_upload(kind):
        uid,_=auth();return upload(uid,kind)

    @app.get('/api/photo-review')
    def photo_review_list():
        uid,_=auth();admin=core.is_admin(uid)
        with core.db(core.USERS_DB) as c:
            if admin and request.args.get('scope')=='pending':
                rows=c.execute("SELECT r.id,r.owner_id,r.kind,r.status,r.created_at,r.reason,a.name FROM pd_photo_reviews r LEFT JOIN pd_driver_applications a ON a.telegram_id=r.owner_id WHERE r.status='pending' ORDER BY r.id LIMIT 200").fetchall()
            else:
                rows=c.execute('''SELECT id,owner_id,kind,status,created_at,reason FROM pd_photo_reviews
                    WHERE owner_id=? AND id IN (SELECT MAX(id) FROM pd_photo_reviews WHERE owner_id=? GROUP BY kind) ORDER BY id DESC''',(uid,uid)).fetchall()
        return jsonify(photos=[dict(r) for r in rows])

    @app.get('/api/photo-review/<int:rid>/image')
    def photo_review_image(rid):
        uid,_=auth()
        with core.db(core.USERS_DB) as c:r=c.execute('SELECT owner_id,jpeg FROM pd_photo_reviews WHERE id=?',(rid,)).fetchone()
        if not r:return jsonify(error='Фото не найдено'),404
        if uid!=r['owner_id'] and not core.is_admin(uid):raise PermissionError('Нет доступа к фото')
        return Response(bytes(r['jpeg']),mimetype='image/jpeg',headers={'Content-Disposition':'inline; filename="review.jpg"','Referrer-Policy':'no-referrer'})

    @app.post('/api/photo-review/<int:rid>/decision')
    def photo_review_decision(rid):
        uid,_=auth()
        if not core.is_admin(uid):raise PermissionError('Решение принимает только диспетчер')
        d=request.get_json(silent=True) or {};decision=d.get('status');reason=d.get('reason','')
        if decision not in ('approved','rejected'):raise ValueError('Некорректное решение')
        if not isinstance(reason,str) or len(reason)>500:raise ValueError('Причина должна быть до 500 символов')
        reason=reason.strip()
        if decision=='approved' and d.get('rules_checked') is not True:raise ValueError('Подтвердите проверку фотографии по правилам')
        if decision=='rejected' and len(reason)<3:raise ValueError('Укажите причину отклонения')
        with core.db(core.USERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM pd_photo_reviews WHERE id=?',(rid,)).fetchone()
            if not r:return jsonify(error='Фото не найдено'),404
            if r['status']!='pending':return jsonify(error='Фото уже рассмотрено или заменено новым. Обновите список'),409
            if decision=='approved':
                if r['kind']=='profile':
                    c.execute('INSERT OR REPLACE INTO pd_profile_avatars_v6 VALUES(?,?,?)',(r['owner_id'],r['jpeg'],int(clock())))
                else:
                    import hashlib
                    if r['kind'].startswith('car_'):
                        others=c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=? AND side IN ('car_front','car_rear','car_interior') AND side<>?",(r['owner_id'],r['kind']))
                        if any(hashlib.sha256(bytes(o['image'])).digest()==hashlib.sha256(bytes(r['jpeg'])).digest() for o in others):raise ValueError('Для разных ракурсов автомобиля нужны разные фотографии')
                    c.execute('''INSERT INTO pd_driver_documents(telegram_id,side,image,updated_at) VALUES(?,?,?,?)
                        ON CONFLICT(telegram_id,side) DO UPDATE SET image=excluded.image,updated_at=excluded.updated_at''',(r['owner_id'],r['kind'],r['jpeg'],core.now().isoformat()))
            c.execute('UPDATE pd_photo_reviews SET status=?,reviewer_id=?,reviewed_at=?,reason=? WHERE id=?',(decision,uid,int(clock()),reason,rid))
        return jsonify(ok=True,status=decision)
