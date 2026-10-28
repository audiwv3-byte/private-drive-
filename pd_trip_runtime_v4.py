"""PRIVATE DRIVE trip runtime. Draft: register explicitly; no import-time writes.
Money is integer EUR cents; the original order price is never overwritten.
"""
import json
import math
import time
from decimal import Decimal, InvalidOperation
from flask import request, jsonify

POLICY = 'pd-trip-v4-20261028'
FREE_SECONDS = 300
WAIT_CENTS_PER_MINUTE = 25
ACTIVE = ('Подтверждена', 'В пути')


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount * 100 != (amount * 100).to_integral_value():
            raise ValueError('Invalid EUR amount')
        return int(amount * 100)
    except InvalidOperation:
        raise ValueError('Invalid EUR amount') from None


def waiting_cents(arrived_at, accepted_at, end):
    if not arrived_at or not accepted_at:
        return 0
    # Never bill time preceding the passenger's tariff acceptance.
    seconds = max(0, end - max(arrived_at + FREE_SECONDS, accepted_at))
    return math.ceil(seconds / 60) * WAIT_CENTS_PER_MINUTE


def schema(core):
    with core.db(core.ORDERS_DB) as c:
        c.executescript('''
CREATE TABLE IF NOT EXISTS pd_trip_runtime_v4 (
 order_id INTEGER PRIMARY KEY, arrived_at INTEGER, started_at INTEGER,
 ended_at INTEGER, wait_accepted_at INTEGER, base_cents INTEGER,
 wait_cents INTEGER NOT NULL DEFAULT 0, final_cents INTEGER,
 lat REAL, lon REAL, accuracy REAL, location_at INTEGER,
 location_pilot_id INTEGER, policy TEXT NOT NULL DEFAULT 'pd-trip-v4-20261028');
CREATE TABLE IF NOT EXISTS pd_trip_extras_v4 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
 request_key TEXT NOT NULL, reason TEXT NOT NULL, amount_cents INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'proposed', proposed_by INTEGER NOT NULL,
 created_at INTEGER NOT NULL, accepted_at INTEGER,
 UNIQUE(order_id,request_key));
CREATE TABLE IF NOT EXISTS pd_trip_events_v4 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
 actor_id INTEGER NOT NULL, event TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pd_booking_capture_v4 (
 order_id INTEGER PRIMARY KEY, amount_cents INTEGER NOT NULL, mode TEXT NOT NULL,
 state TEXT NOT NULL, session_id TEXT UNIQUE, intent_id TEXT UNIQUE,
 checkout_url TEXT, accepted_at INTEGER, paid_at INTEGER,
 policy TEXT NOT NULL, agreed_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pd_booking_cancel_v4 (
 order_id INTEGER PRIMARY KEY, actor_id INTEGER NOT NULL, driver_cancel INTEGER NOT NULL,
 requested_at INTEGER NOT NULL, state TEXT NOT NULL, refund_cents INTEGER NOT NULL DEFAULT 0,
 refund_id TEXT, last_event_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pd_trip_payment_events_v4 (
 event_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL);
''')


def register(app, core, auth, provider=None, clock=None):
    """provider must implement checkout/retrieve/capture/cancel/verify_event.
    No real provider is constructed automatically. Cash/bank stay on their own path.
    """
    schema(core)
    clock = clock or (lambda: int(time.time()))

    def identity():
        return auth()[0]

    def row(c, oid):
        r = c.execute('SELECT o.*,a.pilot_id FROM orders o LEFT JOIN pd_pilot_assignments a '
                      'ON a.order_id=o.id WHERE o.id=?', (oid,)).fetchone()
        if not r:
            raise ValueError('Заказ не найден')
        return r

    def pilot(c, r, uid):
        # Called inside the same transaction as the mutation.
        if r['pilot_id'] != uid:
            raise PermissionError('Заказ назначен другому пилоту')
        if not c.execute("SELECT 1 FROM trip_users.pd_driver_applications WHERE telegram_id=? AND status='approved'", (uid,)).fetchone():
            raise PermissionError('Доступ пилота отсутствует')

    def attach(c):
        c.execute('ATTACH DATABASE ? AS trip_users', (str(core.USERS_DB),))
        c.execute('BEGIN IMMEDIATE')

    def runtime(c, oid):
        c.execute('INSERT OR IGNORE INTO pd_trip_runtime_v4(order_id) VALUES(?)', (oid,))
        return c.execute('SELECT * FROM pd_trip_runtime_v4 WHERE order_id=?', (oid,)).fetchone()

    def event(c, oid, uid, what):
        c.execute('INSERT INTO pd_trip_events_v4(order_id,actor_id,event,created_at) VALUES(?,?,?,?)', (oid, uid, what, clock()))

    def notify(uid, text):
        try:
            core.say(uid, text)
        except Exception:
            core.LOG.exception('Trip notification delivery failed; event remains persisted')

    def view(oid, uid):
        with core.db(core.ORDERS_DB) as c:
            r = row(c, oid)
            if uid not in (r['telegram_id'], r['pilot_id']) and not core.is_admin(uid):
                raise PermissionError('Нет доступа к поездке')
            if uid == r['pilot_id'] and not core.is_admin(uid):
                attach(c)
                pilot(c, r, uid)
            t = c.execute('SELECT * FROM pd_trip_runtime_v4 WHERE order_id=?', (oid,)).fetchone()
            extras = [dict(x) for x in c.execute('SELECT id,reason,amount_cents,state FROM pd_trip_extras_v4 WHERE order_id=? ORDER BY id', (oid,))]
            cap = c.execute('SELECT state,amount_cents FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
            data = dict(t) if t else {'order_id': oid}
            data.update(status=r['status'], server_now=clock(), role='admin' if core.is_admin(uid) else 'pilot' if uid == r['pilot_id'] else 'passenger',
                        free_seconds=FREE_SECONDS, wait_cents_per_minute=WAIT_CENTS_PER_MINUTE,
                        rounding='started_minute', extras=extras, capture=dict(cap) if cap else None,
                        base_cents=data.get('base_cents') or (money(r['price']) if r['price'] else 0))
            if data.get('arrived_at') and not data.get('ended_at'):
                end = data.get('started_at') or clock()
                data['wait_cents'] = waiting_cents(data['arrived_at'], data.get('wait_accepted_at'), end)
            # Sharing stops on completion/cancellation and after reassignment.
            valid_location = (r['status'] in ACTIVE and data.get('location_pilot_id') == r['pilot_id'])
            if not valid_location:
                for k in ('lat', 'lon', 'accuracy', 'location_at', 'location_pilot_id'):
                    data.pop(k, None)
            data['card_capture_available'] = provider is not None
            data['drive_seconds'] = max(0,(data.get('ended_at') or clock())-data['started_at']) if data.get('started_at') else None
            data['waiting_seconds'] = max(0,(data.get('started_at') or data.get('ended_at') or clock())-data['arrived_at']) if data.get('arrived_at') else None
            data['total_service_seconds'] = max(0,(data.get('ended_at') or clock())-data['arrived_at']) if data.get('arrived_at') else None
            data['location_stale'] = not data.get('location_at') or clock() - data['location_at'] > 45
            return data

    @app.get('/api/admin/trip/<int:oid>')
    def pd_v4_admin_trip(oid):
        uid = identity()
        if not core.is_admin(uid):
            raise PermissionError('Информация доступна только администратору')
        data = view(oid, uid)
        with core.db(core.ORDERS_DB) as c:
            order = dict(row(c, oid))
            events = [dict(r) for r in c.execute('SELECT actor_id,event,created_at FROM pd_trip_events_v4 WHERE order_id=? ORDER BY id',(oid,))]
            capture = c.execute('SELECT amount_cents,state,agreed_at,accepted_at,paid_at FROM pd_booking_capture_v4 WHERE order_id=?',(oid,)).fetchone()
            cancellation = c.execute('SELECT actor_id,driver_cancel,requested_at,state,refund_cents FROM pd_booking_cancel_v4 WHERE order_id=?',(oid,)).fetchone()
        with core.db(core.USERS_DB) as c:
            customer = c.execute('SELECT telegram_id,name,phone FROM users WHERE telegram_id=?',(order['telegram_id'],)).fetchone()
            driver = c.execute('SELECT telegram_id,name,phone,city,vehicle,vehicle_year,plate,seats,status FROM pd_driver_applications WHERE telegram_id=?',(order['pilot_id'],)).fetchone() if order['pilot_id'] else None
            photos = [r['side'] for r in c.execute('SELECT side FROM pd_driver_documents WHERE telegram_id=?',(order['pilot_id'],))] if driver else []
        fields = ('id','telegram_id','origin','destination','stop_address','trip_date','trip_time','order_type','passengers','luggage','details','status','price','payment_method','payment_status','distance_km','duration_min','created_at','updated_at')
        data.update(order={k:order[k] for k in fields if k in order},
                    customer=dict(customer) if customer else None,
                    pilot=dict(driver,document_sides=photos) if driver else None,
                    events=events, capture=dict(capture) if capture else None,
                    cancellation=dict(cancellation) if cancellation else None)
        return jsonify(data)

    @app.get('/api/trip/<int:oid>')
    def pd_v4_trip(oid):
        return jsonify(view(oid, identity()))

    @app.post('/api/trip/<int:oid>/waiting-consent')
    def pd_v4_wait_consent(oid):
        uid = identity()
        body = request.get_json(silent=True) or {}
        if body.get('policy') != POLICY or body.get('accept') is not True:
            raise ValueError('Подтвердите тариф: 5 минут бесплатно, далее 0,25 € за начатую минуту')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r = row(c, oid)
            if r['telegram_id'] != uid:
                raise PermissionError('Согласие подтверждает пассажир')
            t = runtime(c, oid)
            if r['status'] not in ('Новая', 'Подтверждена') or t['started_at'] or t['ended_at']:
                raise ValueError('Условия ожидания уже зафиксированы')
            if not t['wait_accepted_at']:
                c.execute('UPDATE pd_trip_runtime_v4 SET wait_accepted_at=? WHERE order_id=?', (clock(), oid))
                event(c, oid, uid, 'waiting_tariff_accepted')
        return jsonify(view(oid, uid))

    @app.post('/api/trip/<int:oid>/location')
    def pd_v4_location(oid):
        uid = identity()
        d = request.get_json(silent=True) or {}
        values = [d.get(k) for k in ('lat', 'lon', 'accuracy')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('Некорректная геопозиция')
        lat, lon, accuracy = values
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 <= accuracy <= 10000:
            raise ValueError('Некорректная геопозиция')
        with core.db(core.ORDERS_DB) as c:
            attach(c)
            r = row(c, oid)
            pilot(c, r, uid)
            if r['status'] not in ACTIVE:
                raise ValueError('Геопозиция доступна только для активной поездки')
            t = runtime(c, oid)
            if t['ended_at']:
                raise ValueError('Поездка окончена')
            c.execute('UPDATE pd_trip_runtime_v4 SET lat=?,lon=?,accuracy=?,location_at=?,location_pilot_id=? WHERE order_id=?',
                      (lat, lon, accuracy, clock(), uid, oid))
        return jsonify(ok=True)

    def transition(oid, action, uid, admin_reason=None):
        text = None
        with core.db(core.ORDERS_DB) as c:
            attach(c)
            r = row(c, oid)
            if admin_reason is not None:
                if not core.is_admin(uid) or not 3 <= len(str(admin_reason)) <= 500:
                    raise PermissionError('Требуется администратор и причина действия')
                if not r['pilot_id']:
                    raise ValueError('Сначала назначьте пилота')
                pilot(c, r, r['pilot_id'])
            else:
                pilot(c, r, uid)
            t = runtime(c, oid)
            if ((action == 'start' and t['started_at'] and r['status'] == 'В пути') or
                (action == 'finish' and t['ended_at'] and r['status'] == 'Выполнена')):
                action = 'noop'
            if action == 'arrive':
                if r['status'] != 'Подтверждена' or t['started_at'] or t['ended_at']:
                    raise ValueError('Прибытие недоступно для текущего статуса')
                if not t['arrived_at']:
                    c.execute('UPDATE pd_trip_runtime_v4 SET arrived_at=?,base_cents=? WHERE order_id=?', (clock(), money(r['price']), oid))
                    event(c, oid, uid, 'arrived')
                    text = f'🚘 Заказ №{oid}: машина прибыла. Первые 5 минут ожидания бесплатны. Далее — 0,25 € за каждую начатую минуту по подтверждённому тарифу.'
            elif action == 'start':
                if r['status'] != 'Подтверждена' or not t['arrived_at'] or t['ended_at']:
                    raise ValueError('Сначала отметьте прибытие')
                if r['payment_status'] != 'Оплачено':
                    raise ValueError('Дождитесь подтверждённой оплаты')
                wait = waiting_cents(t['arrived_at'], t['wait_accepted_at'], clock())
                c.execute('UPDATE pd_trip_runtime_v4 SET started_at=?,wait_cents=? WHERE order_id=?', (clock(), wait, oid))
                c.execute("UPDATE orders SET status='В пути',updated_at=? WHERE id=?", (core.now().isoformat(), oid))
                event(c, oid, uid, 'started')
                text = f'🚘 Заказ №{oid}: поездка началась.'
            elif action == 'finish':
                if r['status'] != 'В пути' or not t['started_at']:
                    raise ValueError('Сначала начните поездку')
                if c.execute("SELECT 1 FROM pd_trip_extras_v4 WHERE order_id=? AND state='proposed'", (oid,)).fetchone():
                    raise ValueError('Пассажир должен принять или отклонить предложенные доплаты')
                extras = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM pd_trip_extras_v4 WHERE order_id=? AND state='accepted'", (oid,)).fetchone()[0]
                final = t['base_cents'] + t['wait_cents'] + extras
                c.execute('UPDATE pd_trip_runtime_v4 SET ended_at=?,final_cents=?,lat=NULL,lon=NULL,accuracy=NULL,location_at=NULL WHERE order_id=?', (clock(), final, oid))
                c.execute("UPDATE orders SET status='Выполнена',updated_at=? WHERE id=?", (core.now().isoformat(), oid))
                event(c, oid, uid, 'completed')
                extra_total = t['wait_cents'] + extras
                text = f'🏁 Поездка №{oid} окончена. Итог: {final/100:.2f} €. Из них основная стоимость: {t["base_cents"]/100:.2f} €, ожидание: {t["wait_cents"]/100:.2f} €, согласованные доплаты: {extras/100:.2f} €. Доплата {extra_total/100:.2f} € ещё не списана. Откройте приложение и оцените водителя.'
            elif action != 'noop':
                raise ValueError('Неизвестное действие')
            if admin_reason is not None and action != 'noop':
                event(c,oid,uid,'admin_'+action+': '+str(admin_reason))
        if text:
            notify(r['telegram_id'], text)
        return view(oid, uid)

    @app.post('/api/trip/<int:oid>/action')
    def pd_v4_action(oid):
        return jsonify(transition(oid, (request.get_json(silent=True) or {}).get('action'), identity()))

    @app.post('/api/trip/<int:oid>/extras')
    def pd_v4_extra(oid):
        uid = identity()
        body = request.get_json(silent=True) or {}
        reason = str(body.get('reason', '')).strip()
        key = str(body.get('request_key', '')).strip()
        amount = body.get('amount_cents')
        if not 3 <= len(reason) <= 300 or not 8 <= len(key) <= 100 or type(amount) is not int or not 1 <= amount <= 100000:
            raise ValueError('Укажите причину и сумму доплаты в евроцентах')
        with core.db(core.ORDERS_DB) as c:
            attach(c)
            r = row(c, oid)
            pilot(c, r, uid)
            if r['status'] not in ACTIVE:
                raise ValueError('Поездка не активна')
            t = runtime(c, oid)
            if t['ended_at']:
                raise ValueError('Итог поездки зафиксирован')
            old = c.execute('SELECT * FROM pd_trip_extras_v4 WHERE order_id=? AND request_key=?', (oid, key)).fetchone()
            if old and (old['reason'] != reason or old['amount_cents'] != amount):
                raise ValueError('Повторный ключ с другими параметрами')
            if not old:
                c.execute('INSERT INTO pd_trip_extras_v4(order_id,request_key,reason,amount_cents,proposed_by,created_at) VALUES(?,?,?,?,?,?)', (oid, key, reason, amount, uid, clock()))
                event(c, oid, uid, 'extra_proposed')
        return jsonify(view(oid, uid))

    @app.post('/api/trip/<int:oid>/extras/<int:eid>')
    def pd_v4_extra_decision(oid, eid):
        uid = identity()
        accept = (request.get_json(silent=True) or {}).get('accept')
        if type(accept) is not bool:
            raise ValueError('Подтвердите или отклоните доплату')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r = row(c, oid)
            if uid != r['telegram_id']:
                raise PermissionError('Доплату подтверждает пассажир')
            if r['status'] not in ACTIVE:
                raise ValueError('Итог поездки зафиксирован')
            state = 'accepted' if accept else 'rejected'
            extra = c.execute('SELECT * FROM pd_trip_extras_v4 WHERE id=? AND order_id=?', (eid, oid)).fetchone()
            if not extra:
                raise ValueError('Доплата не найдена')
            if extra['state'] not in ('proposed', state):
                raise ValueError('Решение уже зафиксировано')
            if extra['state'] == 'proposed':
                c.execute('UPDATE pd_trip_extras_v4 SET state=?,accepted_at=? WHERE id=?', (state, clock(), eid))
                event(c, oid, uid, 'extra_' + state)
        return jsonify(view(oid, uid))

    # Prevent the legacy pilot status buttons from bypassing arrival/wait/final totals.
    for rule in list(app.url_map.iter_rules()):
        if rule.rule == '/api/driver/work/<int:oid>/status':
            def legacy_status(oid):
                target = (request.get_json(silent=True) or {}).get('status')
                action = {'В пути': 'start', 'Выполнена': 'finish'}.get(target)
                return jsonify(transition(oid, action, identity()))
            app.view_functions[rule.endpoint] = legacy_status

    for rule in list(app.url_map.iter_rules()):
        if rule.rule == '/api/driver/work':
            previous_work = app.view_functions[rule.endpoint]
            def timed_work():
                response = previous_work()
                data = response.get_json()
                orders = data.get('orders', [])
                ids = [r['id'] for r in orders]
                if ids:
                    with core.db(core.ORDERS_DB) as c:
                        rows = c.execute('SELECT * FROM pd_trip_runtime_v4 WHERE order_id IN ('+','.join('?' for _ in ids)+')', ids).fetchall()
                    timings = {r['order_id']:dict(r) for r in rows}
                    for order in orders:
                        t = timings.get(order['id'],{})
                        order['drive_seconds'] = max(0,(t.get('ended_at') or clock())-t['started_at']) if t.get('started_at') else None
                        order['waiting_seconds'] = max(0,(t.get('started_at') or t.get('ended_at') or clock())-t['arrived_at']) if t.get('arrived_at') else None
                        order['final_cents'] = t.get('final_cents')
                return jsonify(data)
            app.view_functions[rule.endpoint] = timed_work

    app.config['PD_TRIP_TRANSITION_V4'] = transition
    register_payments(app, core, auth, provider, clock, row, attach, pilot, notify)


def register_payments(app, core, auth, provider, clock, order_row, attach, pilot, notify):
    """Authorization is collected before acceptance; capture only on acceptance.
    Signed provider events are authoritative for payment_status='Оплачено'.
    """
    def configured():
        if provider is None:
            raise ValueError('Автоматическое списание не настроено')
        if provider.mode not in ('test', 'live'):
            raise ValueError('Некорректный режим оплаты')

    def resume_cancellation(oid):
        with core.db(core.ORDERS_DB) as c:
            cancel = c.execute('SELECT * FROM pd_booking_cancel_v4 WHERE order_id=?', (oid,)).fetchone()
            payment = c.execute('SELECT * FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
        if not cancel or not payment:
            return
        if cancel['state'] == 'release_requested' and payment['intent_id']:
            result = provider.cancel(payment['intent_id'], f'pd-v4-cancel-authorization-{oid}')
            if result.get('status') == 'canceled':
                with core.db(core.ORDERS_DB) as c:
                    c.execute("UPDATE pd_booking_cancel_v4 SET state='released' WHERE order_id=? AND state='release_requested'", (oid,))
                    c.execute("UPDATE pd_booking_capture_v4 SET state='canceled' WHERE order_id=? AND state!='paid'", (oid,))
        if cancel['state'] == 'refund_requested' and payment['intent_id']:
            result = provider.refund(payment['intent_id'], cancel['refund_cents'], oid, f'pd-v4-cancel-refund-{oid}-{cancel["refund_cents"]}')
            with core.db(core.ORDERS_DB) as c:
                current = c.execute('SELECT refund_id FROM pd_booking_cancel_v4 WHERE order_id=?', (oid,)).fetchone()
                if current['refund_id'] and current['refund_id'] != result['id']:
                    raise ValueError('Refund id mismatch')
                c.execute('UPDATE pd_booking_cancel_v4 SET refund_id=? WHERE order_id=?', (result['id'], oid))

    @app.post('/api/trip/<int:oid>/cancel')
    def pd_v4_cancel(oid):
        configured()
        uid, _ = auth()
        with core.db(core.ORDERS_DB) as c:
            attach(c)
            r = order_row(c, oid)
            driver = uid == r['pilot_id'] or core.is_admin(uid)
            if not driver and uid != r['telegram_id']:
                raise PermissionError('Нет доступа к отмене')
            if uid == r['pilot_id'] and not core.is_admin(uid):
                pilot(c, r, uid)
            payment = c.execute('SELECT * FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
            if not payment:
                raise ValueError('Этот заказ использует прежний платёжный сценарий')
            existing = c.execute('SELECT * FROM pd_booking_cancel_v4 WHERE order_id=?', (oid,)).fetchone()
            if not existing:
                if r['status'] not in ('Новая','Подтверждена'):
                    raise ValueError('Для начатой поездки требуется ручная сверка')
                refund = 0
                if payment['state'] == 'paid':
                    # Reuse the exact existing cancellation policy, not a new tariff.
                    import pd_prepayment_v3 as previous
                    full = driver or clock() - payment['paid_at'] <= previous.FREE_SECONDS
                    refund = payment['amount_cents'] if full else payment['amount_cents'] * previous.LATE_REFUND_PERCENT // 100
                    state = 'refund_requested'
                elif payment['state'] == 'capturing':
                    state = 'awaiting_capture_check'
                elif payment['intent_id']:
                    state = 'release_requested'
                else:
                    state = 'awaiting_authorization_check'
                c.execute('INSERT INTO pd_booking_cancel_v4(order_id,actor_id,driver_cancel,requested_at,state,refund_cents) VALUES(?,?,?,?,?,?)', (oid,uid,int(driver),clock(),state,refund))
                c.execute("UPDATE orders SET status='Отменена',updated_at=? WHERE id=?", (core.now().isoformat(),oid))
        resume_cancellation(oid)
        with core.db(core.ORDERS_DB) as c:
            state = dict(c.execute('SELECT state,refund_cents FROM pd_booking_cancel_v4 WHERE order_id=?',(oid,)).fetchone())
        return jsonify(ok=True, cancellation=state)

    # Existing cancel buttons delegate V4 payments here; legacy bookings keep their old handler.
    for endpoint in ('pd_passenger_cancel','pd_driver_cancel'):
        previous_handler = app.view_functions.get(endpoint)
        if previous_handler:
            def cancel_dispatch(oid, previous_handler=previous_handler):
                with core.db(core.ORDERS_DB) as c:
                    exists = c.execute('SELECT 1 FROM pd_booking_capture_v4 WHERE order_id=?',(oid,)).fetchone()
                return pd_v4_cancel(oid) if exists else previous_handler(oid)
            app.view_functions[endpoint] = cancel_dispatch

    @app.post('/api/trip/<int:oid>/authorize')
    def pd_v4_authorize(oid):
        configured()
        uid, _ = auth()
        d = request.get_json(silent=True) or {}
        if d.get('policy') != POLICY or d.get('accept') is not True:
            raise ValueError('Подтвердите сумму и списание при принятии заявки пилотом')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r = order_row(c, oid)
            if uid != r['telegram_id']:
                raise PermissionError('Оплату подтверждает пассажир')
            if r['status'] != 'Новая' or r['payment_status'] == 'Оплачено':
                raise ValueError('Заявка уже обработана')
            amount = money(r['price'])
            old = c.execute('SELECT * FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
            if old and (old['amount_cents'] != amount or old['mode'] != provider.mode):
                raise ValueError('Сумма или режим оплаты изменились')
            if old and old['checkout_url']:
                return jsonify(url=old['checkout_url'], replayed=True)
            if not old:
                c.execute("INSERT INTO pd_booking_capture_v4(order_id,amount_cents,mode,state,policy,agreed_at) VALUES(?,?,?,'creating',?,?)", (oid, amount, provider.mode, POLICY, clock()))
        session = provider.checkout(oid, amount, POLICY, f'pd-v4-authorize-{provider.mode}-{oid}-{amount}')
        if bool(session['livemode']) != (provider.mode == 'live') or not session['url'].startswith('https://checkout.stripe.com/'):
            raise ValueError('Неверный ответ платёжной системы')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r = order_row(c, oid)
            p = c.execute('SELECT * FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
            if p['session_id'] and p['session_id'] != session['id']:
                raise ValueError('Требуется сверка платежа')
            c.execute("UPDATE pd_booking_capture_v4 SET session_id=?,checkout_url=?,state=CASE WHEN state='creating' THEN 'checkout' ELSE state END WHERE order_id=?", (session['id'], session['url'], oid))
            if r['status'] != 'Новая':
                raise ValueError('Заявка уже обработана')
        return jsonify(url=session['url'])

    @app.post('/api/trip/<int:oid>/accept')
    def pd_v4_accept(oid):
        configured()
        uid, _ = auth()
        with core.db(core.ORDERS_DB) as c:
            attach(c)
            r = order_row(c, oid)
            pilot(c, r, uid)
            p = c.execute('SELECT * FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
            if not p or p['mode'] != provider.mode or p['amount_cents'] != money(r['price']):
                raise ValueError('Пассажир должен подтвердить рассчитанную сумму картой')
            if p['state'] == 'paid' and r['status'] == 'Подтверждена':
                return jsonify(ok=True, payment_state='paid', replayed=True)
            if r['status'] != 'Новая' or p['state'] not in ('authorized', 'capturing'):
                raise ValueError('Нет действующего подтверждения карты')
            c.execute("UPDATE pd_booking_capture_v4 SET state='capturing',accepted_at=COALESCE(accepted_at,?) WHERE order_id=?", (clock(), oid))
        result = provider.capture(p['intent_id'], p['amount_cents'], f'pd-v4-capture-{provider.mode}-{oid}-{p["amount_cents"]}')
        # Even a synchronous succeeded response must pass through the signed-event ledger.
        return jsonify(ok=True, payment_state='awaiting_webhook', provider_state=result.get('status'))

    @app.post('/api/trip/payments/webhook')
    def pd_v4_payment_webhook():
        configured()
        e = provider.verify_event(request.get_data(), request.headers.get('Stripe-Signature', ''))
        if bool(e['livemode']) != (provider.mode == 'live'):
            raise ValueError('Режим платежа не совпадает')
        obj = e['data']['object']
        meta = obj.get('metadata') or {}
        if meta.get('pd_kind') != 'booking_accept_v4':
            return jsonify(received=True)
        oid = int(meta['order_id'])
        verified_intent = provider.retrieve(obj['payment_intent']) if e['type'] == 'checkout.session.completed' else None
        with core.db(core.ORDERS_DB) as c:
            seen = c.execute('SELECT 1 FROM pd_trip_payment_events_v4 WHERE event_id=?',(e['id'],)).fetchone()
        if seen:
            resume_cancellation(oid)
            return jsonify(received=True)
        needs_release = False
        retry_cancel = False
        notice = None
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r = order_row(c, oid)
            p = c.execute('SELECT * FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
            if not p:
                raise ValueError('Неизвестный платёж')
            if c.execute('SELECT 1 FROM pd_trip_payment_events_v4 WHERE event_id=?', (e['id'],)).fetchone():
                # The dedicated cancel endpoint can resume any interrupted provider call.
                return jsonify(received=True)
            if meta.get('policy') != POLICY or obj.get('currency') != 'eur':
                raise ValueError('Условия платежа не совпадают')
            kind = e['type']
            if kind == 'checkout.session.completed':
                if obj['id'] != p['session_id'] or obj.get('amount_total') != p['amount_cents']:
                    raise ValueError('Сумма платежа не совпадает')
                intent = verified_intent
                if (intent['currency'] != 'eur' or intent['amount'] != p['amount_cents'] or
                    bool(intent['livemode']) != (provider.mode == 'live') or intent['capture_method'] != 'manual' or
                    intent['status'] != 'requires_capture' or intent['amount_capturable'] != p['amount_cents'] or
                    intent.get('metadata',{}).get('order_id') != str(oid) or
                    intent.get('metadata',{}).get('policy') != POLICY):
                    raise ValueError('Подтверждение карты недействительно')
                if p['state'] in ('creating', 'checkout'):
                    c.execute("UPDATE pd_booking_capture_v4 SET state='authorized',intent_id=? WHERE order_id=?", (intent['id'], oid))
                if r['status'] == 'Отменена':
                    c.execute("UPDATE pd_booking_cancel_v4 SET state='release_requested' WHERE order_id=? AND state='awaiting_authorization_check'", (oid,))
                    retry_cancel = True
            elif kind == 'payment_intent.succeeded':
                if (obj['id'] != p['intent_id'] or obj.get('amount_received') != p['amount_cents'] or
                    obj.get('amount') != p['amount_cents'] or obj.get('status') != 'succeeded' or not p['accepted_at']):
                    raise ValueError('Списание не соответствует принятой заявке')
                if r['status'] not in ('Новая','Подтверждена','Отменена'):
                    raise ValueError('Нужна сверка оплаты')
                c.execute("UPDATE pd_booking_capture_v4 SET state='paid',paid_at=COALESCE(paid_at,?) WHERE order_id=?", (int(e['created']), oid))
                if r['status'] == 'Отменена':
                    c.execute("UPDATE pd_booking_cancel_v4 SET state='refund_requested',refund_cents=? WHERE order_id=? AND state IN ('awaiting_capture_check','awaiting_authorization_check','release_requested')", (p['amount_cents'],oid))
                    retry_cancel = True
                else:
                    c.execute("UPDATE orders SET status='Подтверждена',payment_status='Оплачено',payment_method='Онлайн (Stripe)',updated_at=? WHERE id=?", (core.now().isoformat(), oid))
                    notice = f'✅ Заказ №{oid} принят. Списано {p["amount_cents"]/100:.2f} €. Ожидание и другие согласованные доплаты рассчитываются отдельно.'
            elif kind in ('refund.created','refund.updated','refund.failed'):
                cancel = c.execute('SELECT * FROM pd_booking_cancel_v4 WHERE order_id=?',(oid,)).fetchone()
                if (not cancel or obj.get('payment_intent') != p['intent_id'] or
                    obj.get('amount') != cancel['refund_cents'] or
                    cancel['refund_id'] and cancel['refund_id'] != obj['id']):
                    raise ValueError('Возврат не соответствует отмене')
                state = obj.get('status')
                if state not in ('pending','requires_action','succeeded','failed','canceled'):
                    raise ValueError('Неизвестный статус возврата')
                if cancel['state'] != 'succeeded' and e['created'] >= cancel['last_event_at']:
                    c.execute('UPDATE pd_booking_cancel_v4 SET state=?,refund_id=?,last_event_at=? WHERE order_id=?',(state,obj['id'],e['created'],oid))
            elif kind in ('payment_intent.canceled', 'payment_intent.payment_failed'):
                if obj['id'] != p['intent_id']:
                    raise ValueError('Неизвестный платёж')
                if p['state'] != 'paid':
                    c.execute("UPDATE pd_booking_capture_v4 SET state='failed' WHERE order_id=?", (oid,))
            c.execute('INSERT INTO pd_trip_payment_events_v4 VALUES(?,?)', (e['id'], clock()))
        if retry_cancel:
            resume_cancellation(oid)
        if notice:
            notify(r['telegram_id'], notice)
        return jsonify(received=True)

    # Freeze amount/payment changes while authorization/capture is in flight.
    @app.before_request
    def pd_v4_payment_guard():
        if request.method != 'POST':
            return
        d = request.get_json(silent=True) or {}
        endpoint = request.endpoint or ''
        protected = {'admin_status', 'status', 'admin_price_change_pd', 'pd_admin_final_price',
                     'select_cash', 'pd_bank_details', 'create_stripe_checkout', 'pd_passenger_cancel', 'pd_driver_cancel'}
        if endpoint not in protected:
            return
        oid = (request.view_args or {}).get('oid') or d.get('id')
        with core.db(core.ORDERS_DB) as c:
            p = c.execute('SELECT state FROM pd_booking_capture_v4 WHERE order_id=?', (oid,)).fetchone()
        if p:
            if endpoint in ('pd_passenger_cancel','pd_driver_cancel'):
                return
            if endpoint == 'status' and d.get('status') in ('В пути', 'Выполнена') and p['state'] == 'paid':
                return
            raise ValueError('Для нового карточного сценария используйте принятие заявки и сверку оплаты V4')
