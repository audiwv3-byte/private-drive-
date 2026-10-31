"""PRIVATE DRIVE Telegram Mini App server. WSGI entry: application."""
import os, sys, json, hmac, hashlib, time, urllib.parse, io
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import stripe
from flask import Flask, request, jsonify, render_template, send_file

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import Euro_Baltic_Transfer as core

app = Flask(__name__, template_folder='miniapp/templates', static_folder='miniapp/static')
application = app
from pd_request_security import register_request_guard, verify_telegram_user
register_request_guard(app)
import pd_languages
import pd_stops
import pd_fixed_prices
TIMEZONE = ZoneInfo('Europe/Vilnius')
MAX_AGE = 86400


def telegram_user(init_data):
    return verify_telegram_user(init_data, core.TOKEN, max_age=MAX_AGE)


def auth():
    return telegram_user(request.headers.get('X-Telegram-Init-Data', ''))


@app.errorhandler(PermissionError)
def auth_error(exc):
    return jsonify(error=str(exc)), 401


@app.errorhandler(ValueError)
def validation_error(exc):
    return jsonify(error=str(exc)), 400


@app.before_request
def validate_api_json_object():
    # Webhooks need the original raw body for their provider signature.
    if (request.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH')
            and request.is_json and request.endpoint != 'stripe_webhook'):
        if not isinstance(request.get_json(silent=True), dict):
            return jsonify(error='Некорректный запрос. Обновите приложение и повторите попытку.'), 400

@app.errorhandler(400)
@app.errorhandler(415)
def api_request_error(exc):
    if request.path.startswith('/api/'):
        return jsonify(error='Некорректный запрос. Обновите приложение и повторите попытку.'), 400
    return exc


def registered_passenger(uid):
    record = core.user_record(uid)
    return bool(record and str(record['name'] or '').strip() and core.clean_phone(str(record['phone'] or '')))

@app.before_request
def protect_private_information():
    path = request.path.lower()
    protected = path.startswith(('/static/', '/api/pilot', '/api/admin/', '/api/payment'))
    if protected:
        uid, _ = auth()
        if not (core.is_admin(uid) or registered_passenger(uid)):
            return jsonify(error='Информация доступна только после регистрации'), 403

@app.after_request
def private_response_cache(response):
    if request.path.lower().startswith(('/static/', '/api/pilot', '/api/admin/', '/api/payment')):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Vary'] = 'X-Telegram-Init-Data'
    return response


# Passenger checkout remains unavailable until a live payment integration is enabled.
@app.before_request
def pd_release_payment_gate():
    path = request.path
    if request.method == 'POST' and path.startswith('/api/payment/') and path.endswith('/checkout'):
        uid, _ = auth()
        available = app.config.get('PD_PREPAYMENT_AVAILABLE')
        if not available or not available(uid):
            return jsonify(error='Оплата картой пока недоступна. Выберите банковский перевод.'), 503
    if request.method == 'POST' and path == '/api/order':
        body = request.get_json(silent=True) or {}
        if body.get('payment_method') in ('Банковская карта', 'Онлайн (Stripe)'):
            auth()
            return jsonify(error='Оплата картой пока недоступна. Выберите банковский перевод.'), 503

@app.after_request
def pd_release_hide_card_links(response):
    if request.method == 'GET' and request.path.startswith('/api/payment/') and response.status_code == 200 and response.is_json:
        payload = response.get_json(silent=True)
        if isinstance(payload, dict) and 'card_link' in payload:
            payload['card_link'] = ''
            uid, _ = auth()
            enabled = app.config.get('PD_PREPAYMENT_AVAILABLE')
            payload['card_enabled'] = bool(enabled and enabled(uid))
            response.set_data(app.json.dumps(payload))
    return response

@app.get('/api/pilot-info')
def registered_pilot_info():
    return jsonify(email='eurobaltictransfer@gmail.com')

@app.get('/api/pilot-card')
def registered_pilot_card():
    uid, _ = auth()
    if not core.is_admin(uid):
        with core.db(core.ORDERS_DB) as conn:
            booked = conn.execute('SELECT 1 FROM orders WHERE telegram_id=? LIMIT 1', (uid,)).fetchone()
        if not booked:
            return jsonify(error='Карточка пилота доступна после оформления заказа'), 403
    return send_file(ROOT / 'miniapp' / 'static' / 'pilot_card.png', mimetype='image/png', max_age=0)

@app.route('/')
def index():
    return pd_languages.render_index()


@app.get('/api/me')
def me():
    uid, telegram = auth()
    user = core.user_record(uid)
    return jsonify(id=uid, first_name=telegram.get('first_name'), registered=bool(user), name=user['name'] if user else '', phone=user['phone'] if user else '', admin=core.is_admin(uid))


@app.post('/api/register')
def register():
    uid, _ = auth()
    body = request.get_json(force=True)
    if not isinstance(body.get('name'), str) or not isinstance(body.get('phone'), str):
        raise ValueError('Укажите имя и телефон текстом')
    name = ' '.join(str(body.get('name','')).split()).strip()
    phone = str(body.get('phone','')).strip()
    if not (2 <= len(name) <= 80): raise ValueError('Имя должно содержать 2–80 символов')
    validated_phone = core.clean_phone(phone)
    if not validated_phone: raise ValueError('Неверный номер телефона')
    core.initialize()
    core.save_user(uid, name, validated_phone)
    return jsonify(ok=True)



@app.post('/api/register/telegram')
def register_telegram():
    uid, telegram = auth()
    core.initialize()
    user = core.user_record(uid)
    if user and user['phone']:
        return jsonify(registered=True, name=user['name'], phone=user['phone'])
    current = core.state_get(uid)
    if current and current.get('step') not in ('registration_name', 'registration_phone'):
        raise ValueError('В боте есть незавершённый диалог. Завершите его или заполните данные вручную.')
    name = ' '.join(str(telegram.get(k) or '').strip() for k in ('first_name','last_name')).strip()[:80]
    if len(name) < 2:
        raise ValueError('Укажите имя вручную: не менее 2 символов')
    core.state_set(uid, dict(step='registration_phone', name=name, miniapp_telegram=True, resume_order=False))
    return jsonify(registered=False, name=name)

@app.post('/api/register/telegram/cancel')
def cancel_telegram_registration():
    uid, _ = auth()
    state = core.state_get(uid)
    if state and state.get('miniapp_telegram') and state.get('step') == 'registration_phone':
        core.state_clear(uid)
    return jsonify(ok=True)


def pd_pet_extras(data):
    extras = data.get('extras', [])
    if not isinstance(extras, list) or len(extras) > 10 or any(not isinstance(x, str) or len(x) > 100 for x in extras):
        raise ValueError('Некорректные дополнительные услуги')
    return 'Перевозка животного' in extras

def validate_route_data(data):
    if not isinstance(data, dict):
        raise ValueError('Некорректный маршрут')
    if any(not isinstance(data.get(k), str) for k in ('origin', 'destination')):
        raise ValueError('Укажите два адреса')
    if 'roundtrip' in data and type(data['roundtrip']) is not bool:
        raise ValueError('Выберите тип поездки')
    pd_pet_extras(data)
    pd_stops.address(data)
    for key in ('origin', 'destination'):
        pd_map_points.read_point(data, key)

def pd_pet_price(base, data):
    # Единая формула: основная поездка, питомец, трезвый водитель и встреча.
    # Клиент не может передать свою цену; расчёт выполняется на сервере.
    import pd_extra_services
    return pd_extra_services.breakdown(base, data)['total']

@app.post('/api/route')
def route():
    auth()
    d = request.get_json(force=True)
    validate_route_data(d)
    o, dest = str(d.get('origin','')).strip(), str(d.get('destination','')).strip()
    if not (2 <= len(o) <= 200 and 2 <= len(dest) <= 200): raise ValueError('Укажите два адреса')
    if o.casefold() == dest.casefold(): raise ValueError('Начало и конец маршрута совпадают')
    pd_stops.address(d)
    result = {'available': False, 'message':'Предварительная цена по согласованию'}
    try:
        feature,start,end=pd_stops.directions(core,pd_map_points,d,o,dest)
        summary = feature['properties']['summary']
        km, minutes = float(summary['distance'])/1000, float(summary['duration'])/60
        fixed_base=pd_fixed_prices.base(d)
        base_price = fixed_base or core.quote(km, minutes, bool(d.get('roundtrip')))
        price = pd_pet_price(base_price, d)
        return jsonify(available=True, km=round(km,2), minutes=round(minutes),
                      time_text=core.duration_display(minutes), price=price, base_price=base_price, pet_surcharge_percent=10 if pd_pet_extras(d) else 0,
                      start_coordinates=start, end_coordinates=end,
                      road_coordinates=feature['geometry']['coordinates'],
                      note='Приблизительный дорожный маршрут, без учёта пробок')
    except Exception:
        core.LOG.exception('Mini App route service unavailable')
        fixed_base=pd_fixed_prices.base(d)
        if fixed_base:
            return jsonify(available=True,price_only=True,price=pd_pet_price(fixed_base,d),base_price=fixed_base,road_coordinates=[],km=None,time_text='',fixed_price=True)
        return jsonify(result)


@app.post('/api/order')
def create_order():
    uid, _ = auth()
    if not core.user_record(uid): raise ValueError('Сначала заполните профиль')
    d = request.get_json(force=True)
    if not isinstance(d,dict):raise ValueError('Некорректная заявка')
    validate_route_data(d)
    request_key=d.get('request_key')
    fingerprint=''
    if request_key is not None:
        import re
        if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',request_key):
            raise ValueError('Некорректный идентификатор заявки')
        fingerprint=hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!='request_key'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        core.initialize()
        with core.db(core.ORDERS_DB) as conn:
            previous=conn.execute('SELECT id,status,price,request_fingerprint FROM orders WHERE telegram_id=? AND request_key=?',(uid,request_key)).fetchone()
        if previous:
            if previous['request_fingerprint']!=fingerprint:
                raise ValueError('Состав заявки изменился. Начните новую заявку.')
            return jsonify(ok=True,order_id=previous['id'],status=previous['status'],price=previous['price'],replayed=True)
    origin, dest = str(d.get('origin','')).strip(),str(d.get('destination','')).strip()
    if not (2 <= len(origin) <= 200 and 2 <= len(dest) <= 200) or origin.casefold() == dest.casefold():
        raise ValueError('Укажите корректный маршрут')
    date, hour = str(d.get('trip_date','')), str(d.get('trip_time',''))
    if not core.validate_departure(date, hour): raise ValueError('Дата или время поездки неверны')
    method = str(d.get('payment_method', 'Наличными'))
    if method not in ('Наличными', 'Банковская карта', 'Криптовалюта', 'Банковский перевод'):
        raise ValueError('Некорректный способ оплаты')
    passenger_value=d.get('passengers',1)
    if isinstance(passenger_value,bool) or not isinstance(passenger_value,int) or not 1 <= passenger_value <= core.MAX_PASSENGERS:
        raise ValueError('Укажите от 1 до %s пассажиров' % core.MAX_PASSENGERS)
    luggage=str(d.get('luggage','Не указано')).strip()
    if luggage not in ('Не указано','Без багажа','1 чемодан','2 чемодана','3+ чемодана'):
        raise ValueError('Выберите количество багажа')
    has_pet = pd_pet_extras(d)
    stop_address=pd_stops.address(d)
    point_details=pd_map_points.point_details(d)
    details=str(d.get('details','')).strip()
    if len(details)>1000: raise ValueError('Пожелания слишком длинные')
    if has_pet: details += '; С питомцем: доплата 10% к базовой стоимости'
    if 'Встреча с табличкой' in d.get('extras', []):
        details += '; Встреча с табличкой: +20 EUR'
    if 'Трезвый водитель' in d.get('extras', []):
        details += '; Трезвый водитель: пилот управляет автомобилем клиента, тариф поездки x2; выполнение после подтверждения пилотом'
    if point_details:details+='; '+point_details
    if stop_address:details+='\nОстановка: '+stop_address
    km = minutes = None
    fixed_base=pd_fixed_prices.base(d)
    price=pd_pet_price(fixed_base,d) if fixed_base else ''
    try:
        if stop_address:
            feature,_,_=pd_stops.directions(core,pd_map_points,d,origin,dest)
            summary=feature['properties']['summary'];km=float(summary['distance'])/1000;minutes=float(summary['duration'])/60
        else:
            km, minutes = core.route(pd_map_points.route_address(d,'origin',origin),pd_map_points.route_address(d,'destination',dest))
        if km is not None: price=pd_pet_price(fixed_base or core.quote(km,minutes,bool(d.get('roundtrip'))),d)
    except Exception:
        core.LOG.exception('Route not available during booking')
    st=dict(order_type='Туда и обратно' if d.get('roundtrip') else 'В одну сторону',
        origin=origin,destination=dest,trip_date=date,trip_time=hour,passengers=passenger_value,luggage=luggage,
        passenger_count_confirmed=int('passengers' in d),details=details,payment_method=method,price=price,
        distance_km=km,duration_min=minutes,route_source='OpenRouteService' if km is not None else '',
        quote_status='Предварительная' if price else 'Не рассчитано')
    core.initialize()
    if request_key:
        oid,created=core.order_save(uid,st,request_key,fingerprint)
        if not created:
            previous=core.order_find(oid)
            return jsonify(ok=True,order_id=oid,status=previous['status'],price=previous['price'],replayed=True)
    else:
        oid=core.order_save(uid,st)
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('UPDATE orders SET stop_address=? WHERE id=? AND telegram_id=?',(stop_address,oid,uid))
    r=core.order_find(oid)
    try:
        core.say(uid, '✅ Заявка №%s получена. Ожидайте подтверждения пилотом.\n%s'%(oid,core.order_text(r)))
    except Exception: core.LOG.exception('Client notify failed')
    core.notify_admins('🆕 Заявка из Mini App\n'+core.order_text(r,True)+'\nДля принятия: /order '+str(oid))
    return jsonify(ok=True,order_id=oid,status='Новая',price=price)


def pd_refund_labels(rows):
    """Show only completed Stripe refunds; preserve the original payment ledger."""
    result = [dict(row) for row in rows]
    ids = [int(row['id']) for row in result]
    if not ids:
        return result
    with core.db(core.ORDERS_DB) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'pd_adjustments', 'pd_stripe_adjustments'}.issubset(tables):
            return result
        marks = ','.join('?' for _ in ids)
        refunds = conn.execute(
            "SELECT a.order_id,a.amount_eur FROM pd_adjustments a "
            "JOIN pd_stripe_adjustments s ON s.adjustment_id=a.id "
            "WHERE a.kind='refund' AND a.status='Выполнено' "
            "AND s.stripe_refund_id IS NOT NULL AND s.stripe_refund_id!='' "
            "AND a.order_id IN (" + marks + ")", ids).fetchall()
    totals = {}
    for refund in refunds:
        oid = int(refund['order_id'])
        totals[oid] = totals.get(oid, Decimal('0')) + Decimal(str(refund['amount_eur']))
    for row in result:
        refunded = totals.get(int(row['id']), Decimal('0'))
        if refunded <= 0 or row.get('payment_method') != 'Онлайн (Stripe)':
            continue
        row['original_payment_status'] = row.get('payment_status', '')
        row['refunded_eur'] = format(refunded, '.2f')
        paid = Decimal(str(row.get('price') or '0'))
        label = 'Полный возврат' if paid > 0 and refunded >= paid else 'Частичный возврат'
        row['payment_status'] = label + ': ' + format(refunded, '.2f') + ' €'
    return result


@app.after_request
def pd_label_refunded_orders(response):
    if (request.method == 'GET' and response.status_code == 200 and response.is_json
            and request.path in ('/api/orders', '/api/admin/orders')):
        payload = response.get_json(silent=True)
        if isinstance(payload, dict) and isinstance(payload.get('orders'), list):
            payload['orders'] = pd_refund_labels(payload['orders'])
            response.set_data(app.json.dumps(payload))
    return response


@app.get('/api/orders')
def orders():
    uid, _ = auth()
    with core.db(core.ORDERS_DB) as conn:
        rows = conn.execute('SELECT id, origin, destination, trip_date, trip_time, status, price, payment_method, payment_status FROM orders WHERE telegram_id=? ORDER BY id DESC LIMIT 30',(uid,)).fetchall()
    return jsonify(orders=[dict(r) for r in rows])


@app.get('/api/admin/orders')
def admin_orders():
    uid, _=auth()
    if not core.is_admin(uid):raise PermissionError('Нет доступа')
    with core.db(core.ORDERS_DB) as conn:
        rows=conn.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 50').fetchall()
    return jsonify(orders=[dict(r) for r in rows])


@app.post('/api/admin/status')
def admin_status():
    uid, _ = auth()
    if not core.is_admin(uid):
        raise PermissionError('Нет доступа')
    d = request.get_json(force=True)
    oid = int(d.get('id', 0))
    target = str(d.get('status', ''))
    transitions = {
        'Новая': {'Подтверждена', 'Отменена'},
        'Подтверждена': {'В пути', 'Отменена'},
        'В пути': {'Выполнена'},
        'Выполнена': set(),
        'Отменена': set(),
    }
    if target not in ('Подтверждена', 'Отменена', 'В пути', 'Выполнена'):
        raise ValueError('Некорректный статус')
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        r = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if not r: raise ValueError('Заказ не найден')
        current = r['status']
        if target == 'В пути' and r['payment_status'] != 'Оплачено':
            raise ValueError('Дождитесь подтверждённой оплаты перед началом поездки')
        if target not in transitions.get(current, set()):
            raise ValueError('Недопустимое изменение статуса: ' + str(current))
        conn.execute('UPDATE orders SET status=?, updated_at=? WHERE id=?',
                     (target, core.now().isoformat(), oid))
    try:
        markup = core.payment_button(oid) if target == 'Подтверждена' and r['price'] else None
        text = f'🚘 Заказ №{oid}: статус «{target}».'
        if target == 'Выполнена':
            text += '\nПоездка окончена. Спасибо за поездку! Откройте приложение, чтобы оценить водителя.'
            markup = core.types.InlineKeyboardMarkup()
            markup.add(core.types.InlineKeyboardButton('★ Оценить качество сервиса', web_app=core.types.WebAppInfo(url=os.getenv('MINIAPP_URL','https://wilsonpark.pythonanywhere.com').strip())))
        core.say(r['telegram_id'], text, markup)
    except Exception: core.LOG.exception('Notify client failed')
    return jsonify(ok=True)


@app.post('/api/admin/cash-received')
def admin_cash_received_web():
    uid, _ = auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    oid = int((request.get_json(silent=True) or {}).get('id', 0))
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("""CREATE TABLE IF NOT EXISTS pd_cash_receipts (
            order_id INTEGER PRIMARY KEY, amount_eur TEXT NOT NULL,
            admin_telegram_id INTEGER NOT NULL, received_at TEXT NOT NULL
        )""")
        r = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if not r: raise ValueError('Заказ не найден')
        if r['payment_method'] not in ('Наличные', 'Наличными'):
            raise ValueError('Подтверждение вручную разрешено только для наличных')
        if r['payment_status'] not in ('Не оплачено', 'Ожидается оплата наличными'):
            raise ValueError('Платёж уже оплачен или обрабатывается')
        if r['status'] not in ('Подтверждена', 'В пути', 'Выполнена'):
            raise ValueError('Заказ ещё не подтверждён или отменён')
        if r['stripe_session_id'] or r['card_payment_url'] or r['crypto_amount'] or r['crypto_txid']:
            raise ValueError('У заказа есть онлайн-платёж или криптооперация; нельзя отмечать наличные')
        amount = cents_for_order(r['price'])
        received_at = core.now().isoformat()
        conn.execute('INSERT INTO pd_cash_receipts(order_id,amount_eur,admin_telegram_id,received_at) VALUES(?,?,?,?)',
                     (oid, format(Decimal(amount)/100, '.2f'), uid, received_at))
        conn.execute("UPDATE orders SET payment_status='Оплачено',updated_at=? WHERE id=?",
                     (received_at, oid))
    try:
        core.say(r['telegram_id'], f'✅ Заказ №{oid}: получение наличных подтверждено.')
    except Exception: core.LOG.exception('Cash notification failed')
    return jsonify(ok=True,received_at=received_at)


@app.get('/api/admin/cash-receipts')
def admin_cash_receipts_pd():
    uid,_=auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    with core.db(core.ORDERS_DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS pd_cash_receipts (
            order_id INTEGER PRIMARY KEY, amount_eur TEXT NOT NULL,
            admin_telegram_id INTEGER NOT NULL, received_at TEXT NOT NULL
        )""")
        rows=conn.execute('SELECT order_id,amount_eur,received_at FROM pd_cash_receipts ORDER BY received_at DESC LIMIT 100').fetchall()
    return jsonify(receipts=[dict(x) for x in rows])


@app.get('/api/payment/<int:oid>')
def payment(oid):
    uid,_=auth(); r=core.order_find(oid)
    if not r or (r['telegram_id']!=uid and not core.is_admin(uid)):raise PermissionError('Нет доступа')
    return jsonify(id=oid,price=r['price'],status=r['status'],payment_status=r['payment_status'],
       card_link=r['card_payment_url'] if r['status']=='Подтверждена' else '',
       currencies=['USDC','BTC','ETH'], addresses={c: core.CRYPTO_ADDRESSES.get(c, '') if r['status']=='Подтверждена' and r['crypto_currency']==c and r['crypto_amount'] else '' for c in core.PAYMENT_CURRENCIES}, crypto_currency=r['crypto_currency'], crypto_amount=r['crypto_amount'] if r['status']=='Подтверждена' else '')



@app.post('/api/payment/<int:oid>/cash')
def select_cash(oid):
    uid, _ = auth()
    core.initialize()
    r = core.order_find(oid)
    if not r or r['telegram_id'] != uid:
        raise PermissionError('Нет доступа')
    if r['status'] != 'Подтверждена' or not r['price']:
        raise ValueError('Дождитесь подтверждения заказа и цены')
    if r['payment_status'] in ('Оплачено', 'Ожидается банковский перевод', 'Перевод на проверке'):
        raise ValueError('Заказ уже оплачен')
    if r['stripe_session_id']:
        raise ValueError('Для заказа создана ссылка оплаты картой. Смену способа согласуйте с пилотом.')
    with core.db(core.ORDERS_DB) as conn:
        changed = conn.execute("UPDATE orders SET payment_method='Наличные', payment_status='Ожидается оплата наличными',updated_at=? WHERE id=? AND payment_status IN ('Не оплачено','','Ожидается оплата наличными')", (core.now().isoformat(), oid))
        if changed.rowcount != 1:
            raise ValueError('Платёж уже обрабатывается. Обратитесь к администратору.')
    core.notify_admins(f'💶 Заказ №{oid}: пассажир выбрал оплату наличными водителю.')
    return jsonify(ok=True, payment_status='Ожидается оплата наличными')


# Stripe: the secret key is loaded from .env by the core module. No secrets in HTML.
def stripe_key():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    if not key.startswith('sk_test_'):
        raise ValueError('Stripe test mode is not configured')
    stripe.api_key = key
    return key


def cents_for_order(value):
    try:
        amount = Decimal(str(value).replace(',', '.'))
        if not amount.is_finite() or not Decimal('0') < amount <= Decimal('100000'):
            raise ValueError
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise ValueError
        return int(cents)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Некорректная стоимость заказа')


@app.post('/api/payment/<int:oid>/checkout')
def create_stripe_checkout(oid):
    uid, _ = auth()
    core.initialize()
    stripe_key()
    if not os.getenv('STRIPE_WEBHOOK_SECRET', '').startswith('whsec_'):
        raise ValueError('Сначала настройте подписанный Stripe webhook')
    # Serialize requests for the same order. Stripe idempotency protects retries.
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        r = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if not r or (r['telegram_id'] != uid and not core.is_admin(uid)):
            raise PermissionError('Нет доступа')
        if r['status'] != 'Подтверждена':
            raise ValueError('Дождитесь подтверждения заказа')
        if r['payment_status'] in ('Оплачено', 'Ожидается банковский перевод', 'Перевод на проверке'):
            raise ValueError('Заказ уже оплачен')
        amount = cents_for_order(r['price'])
        if r['stripe_session_id'] and r['stripe_amount_cents'] == amount and r['card_payment_url']:
            return jsonify(url=r['card_payment_url'])
        if r['stripe_session_id']:
            raise ValueError('Платёжная сессия уже создана. Обратитесь к пилоту для изменения цены.')
        base = 'https://wilsonpark.pythonanywhere.com'
        session = stripe.checkout.Session.create(
            mode='payment',  # Dynamic payment methods are selected by Stripe Dashboard.
            line_items=[{'price_data': {'currency': 'eur', 'unit_amount': amount,
                'product_data': {'name': f'PRIVATE DRIVE — заказ №{oid}'}}, 'quantity': 1}],
            client_reference_id=str(oid),
            metadata={'order_id': str(oid)},
            success_url=base + '/?payment=return',
            cancel_url=base + '/?payment=cancel',
            expires_at=int(time.time()) + 1800,
            idempotency_key=f'private-drive-test-order-{oid}-cents-{amount}-v1')
        conn.execute("UPDATE orders SET stripe_session_id=?,stripe_amount_cents=?,card_payment_url=?,payment_method='Онлайн (Stripe)',updated_at=? WHERE id=? AND payment_status!='Оплачено'",
            (session.id, amount, session.url, core.now().isoformat(), oid))
    return jsonify(url=session.url)


@app.post('/api/stripe/webhook')
@app.post('/stripe/webhook')
def stripe_webhook():
    stripe_key()
    secret = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()
    if not secret.startswith('whsec_'):
        return jsonify(error='Webhook not configured'), 503
    try:
        event = stripe.Webhook.construct_event(request.get_data(), request.headers.get('Stripe-Signature', ''), secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify(error='Invalid signature'), 400
    if event['type'] != 'checkout.session.completed':
        return jsonify(received=True)
    sess = pd_prepayment_v3.plain(event['data']['object'])
    if (sess.get('metadata') or {}).get('pd_kind') == 'surcharge':
        return pd_stripe_adjustments.handle_checkout_session(core, sess, cents_for_order)
    if sess.get('payment_status') != 'paid' or sess.get('mode') != 'payment':
        return jsonify(received=True)
    try:
        oid = int(sess['metadata']['order_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify(error='Missing order'), 400
    core.initialize()
    updated = False
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        r = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if (not r or r['stripe_session_id'] != sess.get('id')
            or r['stripe_amount_cents'] != sess.get('amount_total')
            or sess.get('currency') != 'eur'):
            return jsonify(error='Order/session mismatch'), 409
        # Amount must still correspond to the currently agreed order price.
        if cents_for_order(r['price']) != sess.get('amount_total'):
            return jsonify(error='Price mismatch'), 409
        if r['payment_status'] != 'Оплачено':
            conn.execute("UPDATE orders SET payment_status='Оплачено',payment_method='Онлайн (Stripe)',updated_at=? WHERE id=? AND payment_status!='Оплачено'",
                         (core.now().isoformat(), oid))
            updated = True
    if updated:
        try:
            core.say(r['telegram_id'], f'✅ PRIVATE DRIVE: заказ №{oid} оплачен картой. Спасибо!')
            core.notify_admins(f'✅ Stripe подтвердил оплату заказа №{oid}: {r["price"]} €')
        except Exception:
            core.LOG.exception('Stripe payment notification failed')
    return jsonify(received=True)


@app.get('/api/payment/<int:oid>/qr/<ticker>')
def crypto_qr(oid, ticker):
    uid, _ = auth()
    r = core.order_find(oid)
    if not r or (r['telegram_id'] != uid and not core.is_admin(uid)):
        raise PermissionError('Нет доступа')
    if r['status'] != 'Подтверждена' or not r['price']:
        raise ValueError('Дождитесь подтверждения заказа и стоимости')
    ticker = ticker.upper()
    if r['crypto_currency'] != ticker or not r['crypto_amount']:
        raise ValueError('Сумма криптоплатежа ещё не согласована')
    if ticker not in core.PAYMENT_CURRENCIES or not core.CRYPTO_ADDRESSES.get(ticker):
        raise ValueError('Адрес оплаты не настроен')
    import qrcode
    out = io.BytesIO()
    qrcode.make(core.CRYPTO_ADDRESSES[ticker]).save(out, format='PNG')
    out.seek(0)
    return send_file(out, mimetype='image/png', max_age=0)



@app.post('/api/admin/price-v2')
def admin_price_change_pd():
    uid, _ = auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    data = request.get_json(force=True)
    try:
        oid = int(data.get('id'))
    except (ValueError, TypeError):
        raise ValueError('Неверный номер заказа')
    # Decimal validation, no floats; never change amounts belonging to Stripe sessions.
    amount_cents = cents_for_order(data.get('price'))
    new_price = format(Decimal(amount_cents)/100, '.2f')
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if row is None: raise ValueError('Заказ не найден')
        if row['status'] not in ('Новая','Подтверждена'):
            raise ValueError('Можно менять цену только новой или подтверждённой поездки')
        if row['payment_status'] not in ('Не оплачено', ''):
            raise ValueError('Изменение цены запрещено: платёж уже обрабатывается')
        if row['stripe_session_id'] or row['card_payment_url']:
            raise ValueError('Сессия оплаты уже создана. Для изменения цены нужна отдельная процедура отмены сессии.')
        if row['crypto_amount'] or row['crypto_txid']:
            raise ValueError('Для заказа назначена криптооплата; сначала отмените её безопасным способом')
        conn.execute("UPDATE orders SET price=?,quote_status='Установлено администратором',updated_at=? WHERE id=?",
                     (new_price,core.now().isoformat(),oid))
    try:
        core.say(row['telegram_id'], f'💶 PRIVATE DRIVE: новая стоимость заказа №{oid} — {new_price} €.')
    except Exception: core.LOG.exception('Price notification failed for order %s',oid)
    return jsonify(ok=True,price=new_price)


@app.get('/api/admin/customers-v2')
def admin_customers_pd():
    uid, _ = auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    with core.db(core.USERS_DB) as conn:
        rows = conn.execute('SELECT telegram_id,name,phone FROM users ORDER BY created_at DESC LIMIT 200').fetchall()
    with core.db(core.ORDERS_DB) as conn:
        stats = conn.execute('SELECT telegram_id,COUNT(*) AS total,MAX(id) AS latest FROM orders GROUP BY telegram_id').fetchall()
    by_id={r['telegram_id']:dict(r) for r in stats}
    return jsonify(customers=[dict(id=r['telegram_id'], name=r['name'],phone=r['phone'],orders=by_id.get(r['telegram_id'],{}).get('total',0),last_order=by_id.get(r['telegram_id'],{}).get('latest')) for r in rows])

# PRIVATE DRIVE FINAL PRICE V1 — guarded correction with history
@app.post('/api/admin/final-price')
def pd_admin_final_price():
    uid, _ = auth()
    if not core.is_admin(uid):
        raise PermissionError('Нет доступа')
    payload = request.get_json(silent=True) or {}
    try:
        oid = int(payload['id'])
    except (ValueError, KeyError, TypeError):
        raise ValueError('Неверный номер заказа')
    amount_cents = cents_for_order(payload.get('price'))
    new_price = format(Decimal(amount_cents) / 100, '.2f')
    reason = ' '.join(str(payload.get('reason') or '').split())
    if not 3 <= len(reason) <= 300:
        raise ValueError('Укажите причину корректировки (3–300 символов)')
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        r = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if r is None:
            raise ValueError('Заказ не найден')
        if r['status'] not in ('Новая', 'Подтверждена', 'В пути', 'Выполнена'):
            raise ValueError('У отменённой поездки цену изменять нельзя')
        if r['payment_status'] not in ('Не оплачено', ''):
            raise ValueError('Изменение запрещено: платёж оплачен либо обрабатывается')
        if r['stripe_session_id'] or r['card_payment_url'] or r['stripe_amount_cents'] is not None:
            raise ValueError('Существует Stripe-сессия. Сначала нужна отдельная процедура её безопасной отмены')
        if r['crypto_amount'] or r['crypto_txid'] or r['crypto_currency']:
            raise ValueError('Назначена криптооплата. Сначала согласуйте её отмену')
        already = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pd_invoices'").fetchone()
        if already and conn.execute('SELECT 1 FROM pd_invoices WHERE order_id=?', (oid,)).fetchone():
            raise ValueError('Счёт уже выпущен; цена в нём зафиксирована')
        conn.execute("CREATE TABLE IF NOT EXISTS pd_price_changes (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, old_price TEXT NOT NULL, new_price TEXT NOT NULL, reason TEXT NOT NULL, admin_telegram_id INTEGER NOT NULL, changed_at TEXT NOT NULL)")
        old_price = r['price'] or ''
        if old_price == new_price:
            return jsonify(ok=True, unchanged=True, price=new_price)
        timestamp = core.now().isoformat()
        conn.execute('INSERT INTO pd_price_changes(order_id,old_price,new_price,reason,admin_telegram_id,changed_at) VALUES(?,?,?,?,?,?)',
                     (oid, old_price, new_price, reason, uid, timestamp))
        conn.execute("UPDATE orders SET price=?,quote_status='Окончательная цена администратора',updated_at=? WHERE id=?",
                     (new_price, timestamp, oid))
    try:
        core.say(r['telegram_id'], f'💶 PRIVATE DRIVE: стоимость заказа №{oid} изменена: {new_price} €. Причина: {reason}')
    except Exception:
        core.LOG.exception('Final price: passenger notification failed for %s', oid)
    return jsonify(ok=True, price=new_price)

@app.get('/api/admin/final-price/history/<int:oid>')
def pd_admin_final_price_history(oid):
    uid, _ = auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    with core.db(core.ORDERS_DB) as conn:
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pd_price_changes'").fetchone()
        rows = conn.execute('SELECT old_price,new_price,reason,changed_at FROM pd_price_changes WHERE order_id=? ORDER BY id DESC LIMIT 30',(oid,)).fetchall() if has else []
    return jsonify(changes=[dict(x) for x in rows])

# PRIVATE DRIVE ADJUSTMENTS V1 — administrative records, not actual transfers
@app.route('/api/admin/adjustments', methods=['GET', 'POST'])
def pd_admin_adjustments():
    uid, _ = auth()
    if not core.is_admin(uid):
        raise PermissionError('Нет доступа')
    with core.db(core.ORDERS_DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS pd_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('surcharge', 'refund')),
            amount_eur TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Черновик',
            admin_telegram_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")
        if request.method == 'GET':
            rows = conn.execute('SELECT id,order_id,kind,amount_eur,reason,status,created_at FROM pd_adjustments ORDER BY id DESC LIMIT 100').fetchall()
            return jsonify(adjustments=[dict(row) for row in rows])
        data = request.get_json(silent=True) or {}
        try:
            oid = int(data.get('id'))
        except (ValueError, TypeError):
            raise ValueError('Некорректный номер заказа')
        kind = data.get('kind')
        if kind not in ('surcharge','refund'):
            raise ValueError('Выберите доплату или возврат')
        cents = cents_for_order(data.get('amount'))
        amount = format(Decimal(cents)/100,'.2f')
        reason = ' '.join(str(data.get('reason') or '').split())
        if not 3 <= len(reason) <= 300:
            raise ValueError('Укажите причину (3–300 символов)')
        conn.execute('BEGIN IMMEDIATE')
        order = conn.execute('SELECT id,status,payment_status,price FROM orders WHERE id=?',(oid,)).fetchone()
        if not order or order['status']=='Отменена':
            raise ValueError('Заказ не найден либо отменён')
        if kind=='refund':
            if order['payment_status']!='Оплачено':
                raise ValueError('Возврат можно запросить только по оплаченному заказу')
            if cents > cents_for_order(order['price']):
                raise ValueError('Возврат не может превышать стоимость заказа')
            total = conn.execute("SELECT amount_eur FROM pd_adjustments WHERE order_id=? AND kind='refund' AND status!='Отменено'",(oid,)).fetchall()
            already = sum((Decimal(row['amount_eur']) for row in total), Decimal('0'))
            if already+Decimal(amount)>Decimal(str(order['price']).replace(',','.')):
                raise ValueError('Сумма заявок на возврат превысит стоимость заказа')
        now=core.now().isoformat()
        cursor=conn.execute("INSERT INTO pd_adjustments(order_id,kind,amount_eur,reason,status,admin_telegram_id,created_at) VALUES(?,?,?,?,?,?,?)",(oid,kind,amount,reason,'Черновик',uid,now))
        return jsonify(ok=True,adjustment_id=cursor.lastrowid,status='Черновик',notice='Создана запись, деньги не перемещались')

@app.post('/api/admin/adjustments/<int:adjustment_id>/cancel')
def pd_cancel_adjustment(adjustment_id):
    uid,_=auth()
    if not core.is_admin(uid):raise PermissionError('Нет доступа')
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT status FROM pd_adjustments WHERE id=?',(adjustment_id,)).fetchone()
        if not row:raise ValueError('Операция не найдена')
        if row['status']!='Черновик':raise ValueError('Отменить можно только черновик')
        conn.execute("UPDATE pd_adjustments SET status='Отменено' WHERE id=?",(adjustment_id,))
    return jsonify(ok=True)

import pd_stripe_adjustments
pd_stripe_adjustments.register(app, core, auth, cents_for_order, stripe_key)

from invoice_extension import register as register_invoice_routes
register_invoice_routes(app, core, auth)



@app.get('/assets/private-drive-approved-design.jpeg')
def pd_public_approved_design():
    return send_file(ROOT / 'miniapp' / 'static' / 'private-drive-approved-design.jpeg', mimetype='image/jpeg', max_age=86400)

@app.get('/assets/private-drive-official-logo.jpeg')
def pd_public_official_logo():
    return send_file(ROOT / 'miniapp' / 'static' / 'private-drive-official-logo.jpeg', mimetype='image/jpeg', max_age=86400)

@app.get('/assets/private-drive-night.png')
def pd_public_night_hero():
    return send_file(ROOT / 'miniapp' / 'static' / 'private-drive-night.png', mimetype='image/png', max_age=86400)

@app.get('/api/admin/customers/<int:customer_id>')
def pd_customer_details(customer_id):
    uid, _ = auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    with core.db(core.USERS_DB) as conn:
        row=conn.execute('SELECT * FROM users WHERE telegram_id=?',(customer_id,)).fetchone()
        if row is None: return jsonify(error='Клиент не найден'),404
        user=dict(row)
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pd_customer_notes'").fetchone()
        note=conn.execute('SELECT notes,updated_at FROM pd_customer_notes WHERE telegram_id=?',(customer_id,)).fetchone() if exists else None
    with core.db(core.ORDERS_DB) as conn:
        rows=conn.execute('SELECT * FROM orders WHERE telegram_id=? ORDER BY id DESC',(customer_id,)).fetchall()
    # A deliberate allowlist excludes session URLs, payment tokens and transaction IDs.
    fields=('id','origin','destination','trip_date','trip_time','status','price','payment_method','payment_status','details','distance_km','duration_min','created_at','updated_at')
    orders=[{k:dict(r).get(k) for k in fields} for r in rows]
    paid=Decimal('0');paid_count=0
    from collections import Counter
    routes=Counter()
    for o in orders:
        if o['status']!='Отменена': routes[str(o['origin'])+' → '+str(o['destination'])]+=1
        if o['payment_status']=='Оплачено':
            paid_count+=1
            try:
                amount=Decimal(str(o['price'] or '0').replace(',','.'))
                if amount.is_finite(): paid+=amount
            except InvalidOperation: pass
    summary=dict(orders=len(orders),completed=sum(o['status']=='Выполнена' for o in orders),active=sum(o['status'] in ('Новая','Подтверждена','В пути') for o in orders),canceled=sum(o['status']=='Отменена' for o in orders),paid_eur=format(paid.quantize(Decimal('0.01')),'.2f'),paid_orders=paid_count,first_order_at=orders[-1]['created_at'] if orders else None,last_order_at=orders[0]['created_at'] if orders else None,frequent_routes=[dict(route=r,count=n) for r,n in routes.most_common(3)])
    return jsonify(customer=dict(id=customer_id,name=user.get('name',''),phone=user.get('phone',''),created_at=user.get('created_at','')),orders=orders,summary=summary,notes=note['notes'] if note else '',notes_updated_at=note['updated_at'] if note else None)

@app.post('/api/admin/customers/<int:customer_id>/notes')
def pd_customer_notes_save(customer_id):
    uid, _=auth()
    if not core.is_admin(uid): raise PermissionError('Нет доступа')
    data=request.get_json(force=True)
    if not isinstance(data,dict) or not isinstance(data.get('notes'),str): raise ValueError('Некорректная заметка')
    notes=data['notes'].strip()
    if len(notes)>2000: raise ValueError('Заметка не должна превышать 2000 символов')
    with core.db(core.USERS_DB) as conn:
        if not conn.execute('SELECT 1 FROM users WHERE telegram_id=?',(customer_id,)).fetchone(): return jsonify(error='Клиент не найден'),404
        conn.execute('CREATE TABLE IF NOT EXISTS pd_customer_notes(telegram_id INTEGER PRIMARY KEY,notes TEXT NOT NULL,updated_at TEXT NOT NULL,admin_id INTEGER NOT NULL)')
        conn.execute('INSERT INTO pd_customer_notes(telegram_id,notes,updated_at,admin_id) VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET notes=excluded.notes,updated_at=excluded.updated_at,admin_id=excluded.admin_id',(customer_id,notes,core.now().isoformat(),uid))
    return jsonify(ok=True)

import pd_service
pd_service.register(app, core, auth)


# Public privacy notice: intentionally available before passenger registration.
@app.get('/privacy')
def pd_privacy_policy():
    return pd_languages.render_document('privacy')



# Public passenger terms in Russian and Lithuanian. No payment behavior changed.
@app.get('/legal')
def pd_passenger_legal():
    return pd_languages.render_document('legal')


# V4 staging-only registration: no provider, no real payments.
import pd_trip_runtime_v4
pd_trip_runtime_v4.register(app, core, auth, provider=None)
import pd_admin_console_v4
pd_admin_console_v4.register(app,core,auth)
@app.get('/assets/pd-trip-runtime-v4.js')
def pd_trip_runtime_v4_asset():
    return send_file(ROOT / 'pd_trip_runtime_v4.js', mimetype='application/javascript', max_age=0)
@app.get('/assets/pd-pilot-cabinet-v4.js')
def pd_pilot_cabinet_v4_asset():
    return send_file(ROOT / 'pd_pilot_cabinet_v4.js', mimetype='application/javascript', max_age=0)
@app.get('/assets/pd-admin-console-v4.js')
def pd_admin_console_v4_asset():
    return send_file(ROOT / 'pd_admin_console_v4.js',mimetype='application/javascript',max_age=0)

if __name__ == '__main__':
    app.run(port=5000,debug=False)

# Signed Telegram referral endpoints. No administrator permissions changed.
import pd_referrals
pd_referrals.register(app, auth)

import pd_map_points
pd_map_points.register(app, auth)

import pd_recent_routes
pd_recent_routes.register(app, auth)

# Separate first-entry forms and private driver applications.
import pd_onboarding
pd_onboarding.register(app, core, auth)

# Optional intermediate stop, preserving old orders and two-address routes.
pd_stops.ensure_schema(core)

# Profile snapshots are private to the authenticated administrator cabinet.
import pd_profile_history
pd_profile_history.register(app,core,auth)

import pd_bank_transfer
pd_bank_transfer.register(app, core, auth, cents_for_order)

# Approved pilots may access only orders assigned to their Telegram identity.
import pd_pilot_dispatch
pd_pilot_dispatch.register(app,core,auth)

# Immutable PDF invoices, restricted to each passenger and administrators.
import pd_invoice_v2
pd_invoice_v2.register(app, core, auth)

import pd_prepayment_v3
pd_prepayment_v3.register(app, core, auth, cents_for_order)

import pd_crypto_manual
pd_crypto_manual.register(app, core, auth, cents_for_order)

import pd_tips_widget
pd_tips_widget.register(app)

# Read-only deployment fingerprint, without sensitive data.
import pd_release_probe
pd_release_probe.register(app)
