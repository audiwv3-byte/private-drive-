"""Service feedback, voluntary passenger profiles and administrator driver view."""
import re
from flask import request, jsonify


def register(app, core, auth):
    core.initialize()
    with core.db(core.USERS_DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pd_passenger_profile (
            telegram_id INTEGER PRIMARY KEY, first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '',
            language_code TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
            home_city TEXT NOT NULL DEFAULT '', preferences TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '')''')
    with core.db(core.ORDERS_DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pd_service_reviews (
            order_id INTEGER PRIMARY KEY, telegram_id INTEGER NOT NULL,
            stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
            comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)''')

    @app.after_request
    def pd_service_private_cache(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'private, no-store, max-age=0'
            response.headers['Vary'] = 'X-Telegram-Init-Data'
        return response

    def admin_auth():
        uid, t = auth()
        if not core.is_admin(uid):
            raise PermissionError('Нет доступа')
        return uid

    def profile(uid):
        with core.db(core.USERS_DB) as c:
            row = c.execute('SELECT * FROM pd_passenger_profile WHERE telegram_id=?', (uid,)).fetchone()
        return dict(row) if row else {}

    def remember(uid, t):
        # Only signed Telegram identity fields; no device/IP/contact-book collection.
        if not core.user_record(uid):
            return
        now = core.now().isoformat()
        values = [str(t.get(k) or '')[:n] for k, n in
                  [('first_name', 80), ('last_name', 80), ('username', 64), ('language_code', 16)]]
        with core.db(core.USERS_DB) as c:
            c.execute('''INSERT INTO pd_passenger_profile
                (telegram_id,first_name,last_name,username,language_code,first_seen_at,last_seen_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                first_name=excluded.first_name,last_name=excluded.last_name,
                username=excluded.username,language_code=excluded.language_code,
                last_seen_at=excluded.last_seen_at''', (uid, *values, now, now))

    original_me = app.view_functions['me']
    def me_extended():
        uid, t = auth()
        remember(uid, t)
        data = original_me().get_json()
        data['profile'] = profile(uid)
        with core.db(core.ORDERS_DB) as c:
            data['pending_reviews'] = c.execute('''SELECT COUNT(*) FROM orders o
                LEFT JOIN pd_service_reviews r ON r.order_id=o.id
                WHERE o.telegram_id=? AND o.status='Выполнена' AND r.order_id IS NULL''', (uid,)).fetchone()[0]
        return jsonify(data)
    app.view_functions['me'] = me_extended

    @app.post('/api/profile/details')
    def pd_profile_details_save():
        uid, t = auth()
        if not core.user_record(uid):
            raise ValueError('Сначала зарегистрируйтесь')
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            raise ValueError('Некорректные данные профиля')
        limits = {'email': 254, 'home_city': 120, 'preferences': 1000}
        out = {}
        for k, limit in limits.items():
            value = d.get(k, '')
            if not isinstance(value, str) or len(value.strip()) > limit:
                raise ValueError('Проверьте длину данных профиля')
            out[k] = value.strip()
        if out['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', out['email']):
            raise ValueError('Проверьте электронную почту')
        remember(uid, t)
        with core.db(core.USERS_DB) as c:
            c.execute('''UPDATE pd_passenger_profile SET email=?,home_city=?,preferences=?,updated_at=?
                WHERE telegram_id=?''', (*out.values(), core.now().isoformat(), uid))
        return jsonify(ok=True, profile=profile(uid))

    def reviewed_orders():
        uid, _ = auth()
        before = request.args.get('before', type=int)
        where = 'o.telegram_id=?' + (' AND o.id<?' if before else '')
        args = (uid, before) if before else (uid,)
        with core.db(core.ORDERS_DB) as c:
            rows = c.execute('''SELECT o.id,o.origin,o.destination,o.stop_address,o.order_type,o.trip_date,o.trip_time,o.status,
                o.price,o.payment_method,o.payment_status,r.stars AS review_stars,
                r.comment AS review_comment,r.updated_at AS review_updated_at
                FROM orders o LEFT JOIN pd_service_reviews r ON r.order_id=o.id
                WHERE ''' + where + ' ORDER BY o.id DESC LIMIT 31', args).fetchall()
        return jsonify(orders=[dict(r) for r in rows[:30]], next_before=rows[29]['id'] if len(rows) > 30 else None)
    app.view_functions['orders'] = reviewed_orders

    @app.post('/api/orders/<int:order_id>/review')
    def pd_submit_service_review(order_id):
        uid, _ = auth()
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            raise ValueError('Выберите оценку')
        stars, comment = d.get('stars'), d.get('comment', '')
        if type(stars) is not int or not 1 <= stars <= 5:
            raise ValueError('Выберите от 1 до 5 звёзд')
        if not isinstance(comment, str) or len(comment.strip()) > 1000:
            raise ValueError('Комментарий — до 1000 символов')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            order = c.execute('SELECT telegram_id,status FROM orders WHERE id=?', (order_id,)).fetchone()
            if order is None or order['telegram_id'] != uid:
                return jsonify(error='Поездка не найдена'), 404
            if order['status'] != 'Выполнена':
                raise ValueError('Оценка доступна после завершения поездки')
            now = core.now().isoformat()
            c.execute('''INSERT INTO pd_service_reviews VALUES(?,?,?,?,?,?)
                ON CONFLICT(order_id) DO UPDATE SET stars=excluded.stars,
                comment=excluded.comment,updated_at=excluded.updated_at''',
                      (order_id, uid, stars, comment.strip(), now, now))
        return jsonify(ok=True, stars=stars)

    original_customer = app.view_functions['pd_customer_details']
    def customer_extended(customer_id):
        admin_auth()
        response = original_customer(customer_id)
        if isinstance(response, tuple):
            return response
        data = response.get_json()
        data['customer']['profile'] = profile(customer_id)
        with core.db(core.ORDERS_DB) as c:
            reviews = [dict(r) for r in c.execute('''SELECT order_id,stars,comment,created_at,updated_at
                FROM pd_service_reviews WHERE telegram_id=? ORDER BY order_id DESC''', (customer_id,))]
        data['reviews'] = reviews
        data['summary']['service_reviews'] = len(reviews)
        data['summary']['service_average'] = round(sum(r['stars'] for r in reviews) / len(reviews), 2) if reviews else None
        by_order = {r['order_id']: r for r in reviews}
        for o in data['orders']:
            o['review'] = by_order.get(o['id'])
        return jsonify(data)
    app.view_functions['pd_customer_details'] = customer_extended

    def all_customers():
        admin_auth()
        with core.db(core.USERS_DB) as c:
            users = [dict(r) for r in c.execute('''SELECT u.telegram_id AS id,u.name,u.phone,
                p.username,p.email,p.home_city,p.last_seen_at FROM users u
                LEFT JOIN pd_passenger_profile p ON p.telegram_id=u.telegram_id
                ORDER BY u.created_at DESC,u.telegram_id DESC''')]
        with core.db(core.ORDERS_DB) as c:
            stats = {r['telegram_id']: dict(r) for r in c.execute('''SELECT telegram_id,COUNT(*) AS orders,
                MAX(id) AS last_order FROM orders GROUP BY telegram_id''')}
        for u in users:
            u.update({k: v for k, v in stats.get(u['id'], {'orders': 0, 'last_order': None}).items() if k != 'telegram_id'})
        return jsonify(customers=users)
    app.view_functions['admin_customers_pd'] = all_customers

    def admin_orders_paged():
        admin_auth()
        before = request.args.get('before', type=int)
        with core.db(core.ORDERS_DB) as c:
            rows = c.execute('SELECT * FROM orders' + (' WHERE id<?' if before else '') +
                             ' ORDER BY id DESC LIMIT 101', (before,) if before else ()).fetchall()
            reviews = {r['order_id']: dict(r) for r in c.execute('SELECT order_id,stars,comment FROM pd_service_reviews')}
        out = [dict(r) for r in rows[:100]]
        for o in out:
            o['review'] = reviews.get(o['id'])
        return jsonify(orders=out, next_before=rows[99]['id'] if len(rows) > 100 else None)
    app.view_functions['admin_orders'] = admin_orders_paged

    @app.get('/api/admin/service-reviews')
    def pd_admin_service_reviews():
        admin_auth()
        before = request.args.get('before', type=int)
        stars = request.args.get('stars', type=int)
        clauses, args = [], []
        if before:
            clauses.append('r.order_id<?'); args.append(before)
        if stars in (1, 2, 3, 4, 5):
            clauses.append('r.stars=?'); args.append(stars)
        with core.db(core.ORDERS_DB) as c:
            summary = c.execute('SELECT COUNT(*) AS total,ROUND(AVG(stars),2) AS average FROM pd_service_reviews').fetchone()
            distribution = {r['stars']: r['n'] for r in c.execute('SELECT stars,COUNT(*) AS n FROM pd_service_reviews GROUP BY stars')}
            rows = c.execute('''SELECT r.*,o.origin,o.destination,o.trip_date FROM pd_service_reviews r
                JOIN orders o ON o.id=r.order_id''' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') +
                             ' ORDER BY r.order_id DESC LIMIT 101', args).fetchall()
        with core.db(core.USERS_DB) as c:
            names = {r['telegram_id']: r['name'] for r in c.execute('SELECT telegram_id,name FROM users')}
        reviews = [dict(r) for r in rows[:100]]
        for r in reviews:
            r['name'] = names.get(r['telegram_id'], 'Клиент')
        return jsonify(reviews=reviews, summary=dict(summary), distribution=distribution,
                       next_before=rows[99]['order_id'] if len(rows) > 100 else None)

    @app.get('/api/admin/driver')
    def pd_admin_driver():
        admin_auth()
        today = core.now().strftime('%d.%m.%Y')
        with core.db(core.ORDERS_DB) as c:
            rows = c.execute('''SELECT * FROM orders WHERE status IN ('Новая','Подтверждена','В пути')
                OR (status='Выполнена' AND trip_date=?) ORDER BY
                CASE status WHEN 'В пути' THEN 0 WHEN 'Подтверждена' THEN 1 WHEN 'Новая' THEN 2 ELSE 3 END,
                substr(trip_date,7,4)||substr(trip_date,4,2)||substr(trip_date,1,2),trip_time,id''', (today,)).fetchall()
        with core.db(core.USERS_DB) as c:
            users = {r['telegram_id']: dict(r) for r in c.execute('SELECT telegram_id,name,phone FROM users')}
        fields = ('id','telegram_id','origin','destination','trip_date','trip_time','status','price',
                  'payment_method','payment_status','details','distance_km','duration_min','order_type','passengers','luggage')
        out = []
        for row in rows:
            r = dict(row)
            o = {k: r.get(k) for k in fields}
            o['customer'] = users.get(o['telegram_id'], {})
            if o['distance_km'] is not None:
                km, costs = core.estimate_costs(o['distance_km'], o['order_type'] == 'Туда и обратно')
                o['estimated_driven_km'], o['estimated_costs_eur'] = km, costs
            out.append(o)
        return jsonify(orders=out)
