#!/usr/bin/env python3
"""Euro Baltic Transfer: single-driver Telegram booking bot.

Uses pyTelegramBotAPI; supports migration of the original users.db/orders.db.
Routing via optional OpenRouteService API key. Does not process card payments.
"""
import json
import io
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

import telebot
from telebot import types
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
TOKEN = os.getenv('BOT_TOKEN', '').strip()
ADMIN_IDS = {int(s) for s in os.getenv('ADMIN_IDS', '').split(',') if s.strip().isdigit()}
ORS_API_KEY = os.getenv('ORS_API_KEY', '').strip()
TZ = ZoneInfo('Europe/Vilnius')
USERS_DB = ROOT / 'users.db'
ORDERS_DB = ROOT / 'orders.db'
CRYPTO_ADDRESSES = {
    'USDC': os.getenv('PAY_USDC_ERC20_ADDRESS', '').strip(),
    'BTC': os.getenv('PAY_BTC_ADDRESS', '').strip(),
    'ETH': os.getenv('PAY_ETH_ADDRESS', '').strip(),
}
PAYMENT_CURRENCIES = ('USDC', 'BTC', 'ETH')

LOG = logging.getLogger('euro_baltic_transfer')
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'), format='%(asctime)s %(levelname)s %(message)s')


def config_decimal(name, default):
    raw = os.getenv(name, str(default)).replace(',', '.').strip()
    try:
        value = Decimal(raw)
        if not value.is_finite() or value < 0:
            raise ValueError(name)
        return value
    except (InvalidOperation, ValueError):
        raise ValueError(f'Invalid {name}: use a non-negative number')


BASE_FARE = config_decimal('BASE_FARE_EUR', '8')
RATE_KM = config_decimal('RATE_PER_KM_EUR', '0.9')
RATE_MIN = config_decimal('RATE_PER_MIN_EUR', '0.0')
MIN_FARE = config_decimal('MIN_FARE_EUR', '25')
ROUNDTRIP_FACTOR = config_decimal('ROUNDTRIP_FACTOR', '2')
DEMAND_MULTIPLIER = config_decimal('DEMAND_MULTIPLIER', '1')
EMPTY_RETURN_FACTOR = config_decimal('EMPTY_RETURN_FACTOR', '0')
DRIVER_FUEL_L100 = config_decimal('FUEL_L_PER_100KM', '7')
DRIVER_FUEL_EUR = config_decimal('FUEL_EUR_PER_L', '1.6')
DRIVER_MAINT_KM = config_decimal('MAINTENANCE_EUR_PER_KM', '0.12')
DRIVER_OTHER_KM = config_decimal('OTHER_EUR_PER_KM', '0.06')
DRIVER_PICKUP_KM = config_decimal('ESTIMATED_PICKUP_KM', '0')
MAX_PASSENGERS = int(os.getenv('MAX_PASSENGERS', '4'))
if MAX_PASSENGERS < 1 or MAX_PASSENGERS > 9:
    raise ValueError('MAX_PASSENGERS must be 1..9')

if not TOKEN:
    raise SystemExit('BOT_TOKEN is missing in .env')
bot = telebot.TeleBot(TOKEN, parse_mode=None, threaded=False)

# Conversation state persisted to SQLite so interruptions/restarts do not erase booking progress.


def db(path):
    connection = sqlite3.connect(str(path), timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA busy_timeout=20000')
    return connection


def ensure_columns(conn, table, columns):
    present = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
    for name, declaration in columns.items():
        if name not in present:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')


def initialize():
    with db(USERS_DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS dialogue_states (
            telegram_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    with db(ORDERS_DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL, order_type TEXT NOT NULL,
            origin TEXT NOT NULL, destination TEXT NOT NULL,
            trip_date TEXT NOT NULL, trip_time TEXT NOT NULL,
            passengers INTEGER NOT NULL, luggage TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Новая',
            price TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        ensure_columns(conn, 'orders', {
            'payment_method': "TEXT NOT NULL DEFAULT 'Не указано'",
            'distance_km': 'REAL', 'duration_min': 'REAL', 'route_source': 'TEXT',
            'quote_status': "TEXT NOT NULL DEFAULT 'Не рассчитано'",
            'updated_at': 'TEXT', 'roundtrip_wait': "TEXT NOT NULL DEFAULT ''",
            'passenger_count_confirmed': 'INTEGER NOT NULL DEFAULT 1',
            'payment_status': "TEXT NOT NULL DEFAULT 'Не оплачено'",
            'card_payment_url': "TEXT NOT NULL DEFAULT ''",
            'crypto_currency': "TEXT NOT NULL DEFAULT ''",
            'crypto_amount': "TEXT NOT NULL DEFAULT ''",
            'crypto_txid': "TEXT NOT NULL DEFAULT ''",
            'stripe_session_id': "TEXT NOT NULL DEFAULT ''",
            'stripe_amount_cents': 'INTEGER',
            'request_key': 'TEXT', 'request_fingerprint': 'TEXT'
        })
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS pd_order_request_key ON orders(telegram_id,request_key) WHERE request_key IS NOT NULL')


def now():
    return datetime.now(TZ)


def user_record(uid):
    with db(USERS_DB) as conn:
        return conn.execute('SELECT * FROM users WHERE telegram_id=?', (uid,)).fetchone()


def save_user(uid, name, phone):
    with db(USERS_DB) as conn:
        conn.execute('''INSERT INTO users(telegram_id,name,phone) VALUES(?,?,?)
            ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name,phone=excluded.phone''',
            (uid, name, phone))


def state_get(uid):
    with db(USERS_DB) as conn:
        r = conn.execute('SELECT payload FROM dialogue_states WHERE telegram_id=?', (uid,)).fetchone()
        return json.loads(r['payload']) if r else None


def state_set(uid, data):
    with db(USERS_DB) as conn:
        conn.execute('''INSERT INTO dialogue_states VALUES(?,?,?)
          ON CONFLICT(telegram_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at''',
          (uid, json.dumps(data, ensure_ascii=False), now().isoformat()))


def state_clear(uid):
    with db(USERS_DB) as conn:
        conn.execute('DELETE FROM dialogue_states WHERE telegram_id=?', (uid,))


def miniapp_launcher(chat_id):
    """Inline web_app button: Telegram supplies signed initData for server auth.

    Reply-keyboard web_app buttons do NOT supply suitable initData.
    """
    mini_url = os.getenv('MINIAPP_URL', 'https://wilsonpark.pythonanywhere.com').strip()
    if not mini_url.startswith('https://'):
        raise ValueError('MINIAPP_URL must be HTTPS')
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('🚘 Открыть PRIVATE DRIVE — оформить поездку',
                                      web_app=types.WebAppInfo(mini_url)))
    say(chat_id, '🚘 PRIVATE DRIVE\nОформление поездки в Telegram:', kb)


def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('🚘 Заказать поездку', '📋 Мои заказы')
    kb.row('👤 Мой профиль', 'ℹ️ Помощь')
    kb.row('🚘 Автомобиль и пилот', '🎁 Пригласить друга')
    return kb


def cancel_menu(buttons=None):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if buttons:
        for row in buttons:
            kb.row(*row)
    kb.row('❌ Отмена')
    return kb


def admin_menu():
    return cancel_menu([('📋 Все заказы', '👥 Пользователи'), ('🏠 Главное меню',)])


def say(chat_id, message, reply_markup=None):
    return bot.send_message(chat_id, message, reply_markup=reply_markup)


def is_admin(uid):
    return uid in ADMIN_IDS


def notify_admins(message):
    for uid in ADMIN_IDS:
        try:
            say(uid, message)
        except Exception:
            LOG.exception('Failed to notify admin %s', uid)


def start_registration(message, resume_order=False):
    state_set(message.from_user.id, {'step': 'registration_name', 'resume_order': resume_order})
    say(message.chat.id, '👋 Euro Baltic Transfer\n\nДля заявки нужны имя и телефон.\nШаг 1/2: введите имя:', cancel_menu())


def begin_order(message):
    uid = message.from_user.id
    if not user_record(uid):
        start_registration(message, True)
        return
    state_set(uid, {'step': 'order_type'})
    say(message.chat.id, '🚘 Выберите тип поездки:',
        cancel_menu([('🚘 В одну сторону', '🔄 Туда и обратно')]))


def clean_phone(raw):
    if not re.fullmatch(r'\+?[0-9\s().-]+', raw):
        return None
    digits = re.sub(r'\D', '', raw)
    if not 7 <= len(digits) <= 15:
        return None
    return ('+' if raw.startswith('+') else '') + digits


def validate_departure(date_text, time_text):
    try:
        date = datetime.strptime(date_text, '%d.%m.%Y').date()
        hm = datetime.strptime(time_text, '%H:%M').time()
    except ValueError:
        return False
    departure = datetime.combine(date, hm, tzinfo=TZ)
    return departure > now() and departure <= now() + timedelta(days=365)


def ors_request(url, data=None):
    """Retry transient ORS errors; fail cleanly if ORS remains unavailable."""
    request = urllib.request.Request(
        url, data=data,
        headers={
            'Accept': 'application/geo+json' if url.endswith('/geojson') else 'application/json',
            'User-Agent': 'EuroBalticTransfer/1.1',
            **({'Authorization': ORS_API_KEY, 'Content-Type': 'application/json'} if data else {}),
        },
        method='POST' if data else 'GET',
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            LOG.warning('ORS temporary HTTP %s, attempt %s/3', exc.code, attempt + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                raise
            LOG.warning('ORS connection error %s, attempt %s/3', type(exc).__name__, attempt + 1)
        time.sleep((1, 3)[attempt])
    raise RuntimeError('OpenRouteService unavailable')


@lru_cache(maxsize=512)
def _geocode_cached(address):
    query = urllib.parse.urlencode({'api_key': ORS_API_KEY, 'text': address, 'size': 1})
    doc = ors_request('https://api.openrouteservice.org/geocode/search?' + query)
    features = doc.get('features') or []
    if not features:
        raise ValueError(f'Не удалось определить адрес «{address}»')
    coords = features[0]['geometry']['coordinates']
    return (float(coords[0]), float(coords[1]))


def geocode(address):
    # Allow coordinates selected on the Mini App map (lat,lon).
    match = re.fullmatch(r'\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*', address)
    if match:
        lat, lon = (float(x) for x in match.groups())
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return [lon, lat]
    return list(_geocode_cached(' '.join(address.strip().split())))


def route(origin, destination):
    """Returns (distance_km, duration_min) from route directions or None when not configured."""
    if not ORS_API_KEY:
        return None
    start, end = geocode(origin), geocode(destination)
    body = json.dumps({'coordinates': [start, end]}).encode('utf-8')
    data = ors_request('https://api.openrouteservice.org/v2/directions/driving-car', body)
    summary = data['routes'][0]['summary']
    return (float(summary['distance']) / 1000, float(summary['duration']) / 60)


def euro(value):
    return str(Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def quote(distance_km, duration_min, roundtrip=False):
    """Configurable estimate; not an offer of live traffic / demand-based pricing."""
    distance, duration = Decimal(str(distance_km)), Decimal(str(duration_min))
    if distance < 0 or duration < 0:
        raise ValueError('Distance or duration cannot be negative')
    price = max(MIN_FARE, BASE_FARE + RATE_KM * distance + RATE_MIN * duration)
    if roundtrip:
        price *= ROUNDTRIP_FACTOR
    price *= DEMAND_MULTIPLIER
    # Optional configured empty-return surcharge. Zero by default; avoid silently charging customers.
    price += EMPTY_RETURN_FACTOR * RATE_KM * distance
    return euro(price)


def estimate_costs(distance_km, is_roundtrip):
    # Operational estimate displayed only to administrator. Return leg assumed for one way.
    d = Decimal(str(distance_km))
    driven = d * (Decimal('2') if not is_roundtrip else ROUNDTRIP_FACTOR) + DRIVER_PICKUP_KM
    cost = driven * (DRIVER_FUEL_L100 / 100 * DRIVER_FUEL_EUR + DRIVER_MAINT_KM + DRIVER_OTHER_KM)
    return euro(driven), euro(cost)


def order_save(uid, st, request_key=None, request_fingerprint=''):
    with db(ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if request_key:
            existing=conn.execute('SELECT id,request_fingerprint FROM orders WHERE telegram_id=? AND request_key=?',(uid,request_key)).fetchone()
            if existing:
                if existing['request_fingerprint']!=request_fingerprint:
                    raise ValueError('Состав заявки изменился. Начните новую заявку.')
                return existing['id'],False
        cur = conn.execute('''INSERT INTO orders
          (telegram_id,order_type,origin,destination,trip_date,trip_time,passengers,luggage,
          details,status,price,payment_method,distance_km,duration_min,route_source,quote_status,
          updated_at,roundtrip_wait,passenger_count_confirmed,request_key,request_fingerprint)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
          uid, st['order_type'], st['origin'], st['destination'], st['trip_date'], st['trip_time'],
          st['passengers'], st['luggage'], st.get('details',''), 'Новая', st.get('price',''),
          st['payment_method'], st.get('distance_km'), st.get('duration_min'),
          st.get('route_source',''), st.get('quote_status','Не рассчитано'), now().isoformat(),
          st.get('roundtrip_wait',''), int(st.get('passenger_count_confirmed', 1)), request_key, request_fingerprint))
        return (cur.lastrowid,True) if request_key else cur.lastrowid


def order_find(oid):
    with db(ORDERS_DB) as conn:
        return conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()


def duration_display(minutes):
    """Human-readable approximate duration in Russian."""
    total = max(0, round(float(minutes)))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f'{hours} ч {mins} мин'
    if hours:
        return f'{hours} ч'
    return f'{mins} мин'


def extra_wishes_prompt():
    return ("📝 Дополнительные пожелания к поездке?\n\n"
            "🌡️ Температура в салоне\n"
            "🎵 Музыка или тишина\n"
            "🛑 Остановки по маршруту\n"
            "👶 Детское кресло или бустер\n"
            "🐾 Перевозка питомцев\n"
            "🧳 Нестандартный багаж\n\n"
            "Напишите пожелания или нажмите «✅ Нет пожеланий».")


def wishes_menu():
    return cancel_menu([('✅ Нет пожеланий',)])


def order_text(order, private=False):
    r = order
    output = [f"🚘 Заказ №{r['id']}", f"Маршрут: {r['origin']} → {r['destination']}",
        f"Тип: {r['order_type']}", f"Дата: {r['trip_date']} в {r['trip_time']} (Вильнюс)",
        f"Оплата: {r['payment_method']}", f"Примечание: {r['details'] or 'Нет'}",
        f"Статус: {r['status']}", f"Цена: {r['price'] + ' €' if r['price'] else 'По согласованию'}"]
    if r['distance_km'] is not None:
        output.append(f"Маршрут: {r['distance_km']:.1f} км / ~{duration_display(r['duration_min'])} (без учёта пробок)")
    output.append(f"Платёж: {r['payment_status']}")
    if private:
        if r['crypto_currency']:
            output.append(f"Криптовалюта: {r['crypto_currency']} / {r['crypto_amount'] or 'сумма уточняется'}")
        if r['crypto_txid']:
            output.append(f"Заявленный TXID: {r['crypto_txid']}")
        usr = user_record(r['telegram_id'])
        output.append(f"Клиент: {usr['name'] if usr else '—'}; телефон: {usr['phone'] if usr else '—'}")
        output.append(f"Telegram ID: {r['telegram_id']}")
        if r['distance_km'] is not None:
            km, costs = estimate_costs(r['distance_km'], r['order_type'] == 'Туда и обратно')
            output.append(f"Внутренняя оценка: пробег {km} км, переменные расходы {costs} € (без налогов/времени)")
    return '\n'.join(output)


def preview(st):
    parts = [f"🚘 {st['order_type']}", f"📍 {st['origin']} → {st['destination']}",
       f"📅 {st['trip_date']} {st['trip_time']} (Вильнюс)",
       f"💳 {st['payment_method']}"]
    if st.get('roundtrip_wait'):
        parts.append('⏳ Обратная поездка: ' + st['roundtrip_wait'])
    if st.get('details'):
        parts.append('📝 ' + st['details'])
    if st.get('distance_km') is not None:
        parts.append(f"🗺️ {st['distance_km']:.1f} км\n⏱️ Время в пути: примерно {duration_display(st['duration_min'])} (без учёта пробок)")
    parts.append('💶 Ориентировочная цена: ' + (st['price']+' €' if st.get('price') else 'по согласованию'))
    parts.append('Цена требует подтверждения водителем.')
    return '\n'.join(parts)


def process(message):
    uid = message.from_user.id
    st = state_get(uid)
    if not st:
        say(message.chat.id, 'Выберите действие в меню.', menu())
        return
    step = st['step']
    text = (message.text or '').strip()
    if step != 'registration_phone' and message.content_type != 'text':
        say(message.chat.id, 'Введите ответ текстом или выберите кнопку.')
        return

    if step == 'registration_name':
        name = ' '.join(text.split())
        if not 2 <= len(name) <= 80:
            say(message.chat.id, 'Имя должно содержать 2–80 символов.')
            return
        st.update(step='registration_phone', name=name)
        state_set(uid, st)
        # Request-contact buttons must be created with request_contact=True.
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add(types.KeyboardButton('📱 Отправить свой номер', request_contact=True))
        kb.add('❌ Отмена')
        say(message.chat.id, 'Шаг 2/2: отправьте свой номер кнопкой ниже или введите +370...', kb)
        return
    if step == 'registration_phone':
        if message.content_type == 'contact':
            contact = message.contact
            if contact.user_id is not None and contact.user_id != uid:
                say(message.chat.id, 'Отправьте собственный номер телефона.')
                return
            phone = clean_phone(contact.phone_number)
        else:
            phone = clean_phone(text)
        if not phone:
            say(message.chat.id, 'Неверный телефон. Используйте международный формат, например +37061234567.')
            return
        save_user(uid, st['name'], phone)
        resume = st.get('resume_order', False)
        state_clear(uid)
        say(message.chat.id, '✅ Регистрация завершена.', menu())
        notify_admins(f"👤 Новая регистрация: {st['name']}, {phone}, Telegram {uid}")
        if resume:
            begin_order(message)
        return
    if step == 'order_type':
        mapping = {'🚘 В одну сторону': 'В одну сторону', '🔄 Туда и обратно': 'Туда и обратно'}
        if text not in mapping:
            say(message.chat.id, 'Выберите тип поездки кнопкой.')
            return
        st.update(order_type=mapping[text], step='origin')
        say(message.chat.id, '📍 Укажите адрес отправления (город, улица, номер):', cancel_menu())
    elif step == 'origin':
        if not 3 <= len(text) <= 200:
            say(message.chat.id, 'Укажите более точный адрес (3–200 символов).')
            return
        st.update(origin=text, step='destination')
        say(message.chat.id, '🏁 Укажите адрес назначения (город, улица, номер):')
    elif step == 'destination':
        if not 3 <= len(text) <= 200 or text.casefold() == st['origin'].casefold():
            say(message.chat.id, 'Введите другой корректный адрес назначения.')
            return
        st.update(destination=text, step='trip_date')
        say(message.chat.id, '📅 Дата выезда (ДД.ММ.ГГГГ):')
    elif step == 'trip_date':
        try:
            d = datetime.strptime(text, '%d.%m.%Y').date()
            if d < now().date() or d > (now() + timedelta(days=365)).date():
                raise ValueError
        except ValueError:
            say(message.chat.id, 'Дата неверна. Введите ДД.ММ.ГГГГ, не более года вперёд.')
            return
        st.update(trip_date=d.strftime('%d.%m.%Y'), step='trip_time')
        say(message.chat.id, '🕒 Время выезда по Вильнюсу (ЧЧ:ММ):')
    elif step == 'trip_time':
        if not validate_departure(st['trip_date'], text):
            say(message.chat.id, 'Некорректное или прошедшее время. Формат ЧЧ:ММ, время Вильнюса.')
            return
        st.update(trip_time=text, passengers=1, passenger_count_confirmed=0,
                  luggage='Стандартный багаж',
                  step='roundtrip_wait' if st['order_type'] == 'Туда и обратно' else 'payment_method')
        if st['step'] == 'roundtrip_wait':
            say(message.chat.id, '⏳ Когда планируется обратный путь? Укажите дату/время или «По договорённости».')
        else:
            say(message.chat.id, '💳 Как планируете оплатить?', cancel_menu([('💶 Наличные', '💳 Безналичная')]))
    elif step == 'roundtrip_wait':
        if not 2 <= len(text) <= 100:
            say(message.chat.id, 'Укажите время обратного пути (до 100 символов).')
            return
        st.update(roundtrip_wait=text, step='payment_method')
        say(message.chat.id, '💳 Как планируете оплатить?', cancel_menu([('💶 Наличные', '💳 Безналичная')]))
    elif step == 'payment_method':
        options = {'💶 Наличные': 'Наличные', '💳 Безналичная': 'Безналичная (по согласованию)'}
        if text not in options:
            say(message.chat.id, 'Выберите способ оплаты кнопкой.')
            return
        st.update(payment_method=options[text], step='details')
        say(message.chat.id, extra_wishes_prompt(), wishes_menu())
    elif step == 'details':
        if len(text) > 700:
            say(message.chat.id, 'Слишком длинный комментарий (максимум 700 символов).')
            return
        st['details'] = '' if text.casefold() in ('нет', '✅ нет пожеланий') else text
        st.update(step='confirm', quote_status='Не рассчитано')
        if ORS_API_KEY:
            try:
                distance, duration = route(st['origin'], st['destination'])
                st.update(distance_km=round(distance, 2), duration_min=round(duration, 1),
                  route_source='OpenRouteService', quote_status='Предварительно')
                st['price'] = quote(distance, duration, st['order_type'] == 'Туда и обратно')
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError,
                    IndexError, TypeError, TimeoutError, RuntimeError, OSError) as error:
                LOG.warning('Routing failed (will request manual quote): %s', error)
        state_set(uid, st)
        say(message.chat.id, 'Проверьте заявку:\n\n' + preview(st),
            cancel_menu([('✅ Подтвердить заявку', '✏️ Начать заново')]))
        return
    elif step == 'confirm':
        if text == '✏️ Начать заново':
            begin_order(message)
            return
        if text != '✅ Подтвердить заявку':
            say(message.chat.id, 'Подтвердите заявку или начните заново.')
            return
        if not validate_departure(st['trip_date'], st['trip_time']):
            say(message.chat.id, 'Выбранное время уже прошло. Начните оформление заново.')
            begin_order(message)
            return
        order_id = order_save(uid, st)
        state_clear(uid)
        say(message.chat.id,
            f'✅ Заявка №{order_id} принята и ожидает подтверждения водителем.\n'
            'Это не окончательное подтверждение поездки или цены.', menu())
        for admin_uid in ADMIN_IDS:
            try:
                say(admin_uid, '🆕 Новая заявка!\n' + order_text(order_find(order_id), True),
                    status_buttons(order_id))
            except Exception:
                LOG.exception('Cannot notify admin about order %s', order_id)
        return
    else:
        state_clear(uid)
        say(message.chat.id, 'Диалог сброшен. Начните снова.', menu())
        return
    state_set(uid, st)


def miniapp_payment_button():
    url = os.getenv('MINIAPP_URL', 'https://wilsonpark.pythonanywhere.com').strip()
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('💳 Открыть оплату в PRIVATE DRIVE', web_app=types.WebAppInfo(url)))
    return kb


def payment_button(oid):
    # The app owns payment selection and its transactional checks.
    return miniapp_payment_button()


def payment_menu(oid):
    return miniapp_payment_button()


def crypto_menu(oid):
    kb = types.InlineKeyboardMarkup(row_width=3)
    for ticker in PAYMENT_CURRENCIES:
        kb.add(types.InlineKeyboardButton(ticker, callback_data=f'pay:{oid}:{ticker}'))
    return kb


def payment_admin_buttons(oid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton('✅ Платёж получен', callback_data=f'paid:{oid}:yes'))
    kb.add(types.InlineKeyboardButton('❌ Не поступил', callback_data=f'paid:{oid}:no'))
    return kb


def cash_receipt_button(oid):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('✅ Получил наличные', callback_data=f'cashpaid:{oid}'))
    return kb


def qr_for_address(chat_id, ticker, address):
    try:
        import qrcode
        img = qrcode.make(address)
        image_bytes = io.BytesIO()
        img.save(image_bytes, format='PNG')
        image_bytes.seek(0)
        image_bytes.name = 'wallet.png'
        bot.send_photo(chat_id, image_bytes, caption=f'{ticker}: QR-код адреса (БЕЗ суммы)')
    except ImportError:
        LOG.warning('qrcode not installed; using text-only address')
    except Exception:
        LOG.exception('QR sending failed')


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.startswith('pay:'))
def handle_payment(call):
    """Old messages remain clickable, but cannot bypass the app's payment checks."""
    try:
        _, oid, action = call.data.split(':', 2)
        r = order_find(int(oid))
    except (ValueError, AttributeError):
        bot.answer_callback_query(call.id, 'Неверный заказ')
        return
    if not r or call.from_user.id != r['telegram_id']:
        bot.answer_callback_query(call.id, 'Нет доступа')
        return
    if r['payment_status'] == 'Оплачено':
        bot.answer_callback_query(call.id, 'Заказ уже оплачен')
        return
    if r['status'] != 'Подтверждена' or not r['price']:
        bot.answer_callback_query(call.id, 'Сначала дождитесь подтверждения поездки и цены')
        return
    bot.answer_callback_query(call.id, 'Откройте оплату в приложении')
    say(call.message.chat.id,
        f'Заказ №{r["id"]}. Способы оплаты и актуальный статус доступны в PRIVATE DRIVE: '
        '«Поездки» → «Оплата / детали».', miniapp_payment_button())


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.startswith('cashpaid:'))
def admin_cash_received(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, 'Нет доступа')
        return
    bot.answer_callback_query(call.id, 'Подтвердите поступление в приложении')
    say(call.message.chat.id, 'Подтверждайте наличные в административной панели PRIVATE DRIVE. '
        'Там проверяются статус заказа, способ оплаты и журнал поступлений.', miniapp_payment_button())


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.startswith('claim:'))
def claim_payment(call):
    try:
        _, oid, coin = call.data.split(':', 2)
        r = order_find(int(oid))
    except (ValueError, AttributeError):
        bot.answer_callback_query(call.id, 'Неверный заказ')
        return
    if not r or r['telegram_id'] != call.from_user.id:
        bot.answer_callback_query(call.id, 'Нет доступа')
        return
    bot.answer_callback_query(call.id, 'Проверьте платёж в приложении')
    say(call.message.chat.id, 'Актуальный статус и проверка оплаты доступны в PRIVATE DRIVE.', miniapp_payment_button())


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.startswith('paid:'))
def admin_verify_payment(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, 'Нет доступа')
        return
    bot.answer_callback_query(call.id, 'Проверьте платёж в приложении')
    say(call.message.chat.id, 'Проверьте фактическое поступление и подтвердите нужный платёж '
        'в административной панели PRIVATE DRIVE.', miniapp_payment_button())


@bot.message_handler(commands=['crypto'])
def admin_crypto_amount(message):
    if not is_admin(message.from_user.id):
        return
    say(message.chat.id, 'Укажите точную сумму криптоплатежа в административной панели PRIVATE DRIVE. '
        'Приложение проверит, что другой платёж по заказу не обрабатывается.', miniapp_payment_button())


@bot.message_handler(commands=['paylink'])
def admin_card_link(message):
    if not is_admin(message.from_user.id):
        return
    say(message.chat.id, 'Оплата картой пока отключена. Используйте доступные способы оплаты '
        'в PRIVATE DRIVE.', miniapp_payment_button())



# Referral MVP: points are not money and never change a fare automatically.
def referral_initialize():
    with db(USERS_DB) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS ref_members(uid INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, inviter INTEGER, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ref_rewards(invitee INTEGER PRIMARY KEY, inviter INTEGER NOT NULL, order_id INTEGER NOT NULL, points INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS ref_promos(code TEXT PRIMARY KEY, points INTEGER NOT NULL CHECK(points>0), max_uses INTEGER NOT NULL CHECK(max_uses>0), active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS ref_redemptions(uid INTEGER NOT NULL, code TEXT NOT NULL, points INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(uid,code));
        ''')


def referral_touch(uid, payload=''):
    import secrets
    with db(USERS_DB) as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM ref_members WHERE uid=?',(uid,)).fetchone()
        if row:
            return False
        inviter=None
        if re.fullmatch(r'ref_[A-Za-z0-9_-]{16}',payload) and not user_record(uid):
            parent=c.execute('SELECT uid FROM ref_members WHERE code=?',(payload[4:],)).fetchone()
            if parent and parent['uid'] != uid:
                inviter=parent['uid']
        c.execute('INSERT INTO ref_members VALUES(?,?,?,?)',
                  (uid,secrets.token_urlsafe(12),inviter,now().isoformat()))
        return inviter is not None


def referral_sync(uid):
    # Only real completed, paid rides qualify. Stripe Sandbox is excluded in this MVP.
    with db(USERS_DB) as c:
        friends=c.execute('SELECT uid FROM ref_members WHERE inviter=?',(uid,)).fetchall()
    for friend in friends:
        with db(ORDERS_DB) as orders:
            ride=orders.execute("SELECT id FROM orders WHERE telegram_id=? AND status='Выполнена' AND payment_status='Оплачено' AND COALESCE(stripe_session_id,'')='' ORDER BY id LIMIT 1",(friend['uid'],)).fetchone()
        if ride:
            with db(USERS_DB) as c:
                c.execute('INSERT OR IGNORE INTO ref_rewards VALUES(?,?,?,?)',(friend['uid'],uid,ride['id'],1))


def referral_show(message):
    if message.chat.type != 'private':
        return
    uid=message.from_user.id
    referral_touch(uid)
    referral_sync(uid)
    with db(USERS_DB) as c:
        member=c.execute('SELECT * FROM ref_members WHERE uid=?',(uid,)).fetchone()
        invited=c.execute('SELECT COUNT(*) FROM ref_members WHERE inviter=?',(uid,)).fetchone()[0]
        earned=c.execute('SELECT COALESCE(SUM(points),0) FROM ref_rewards WHERE inviter=?',(uid,)).fetchone()[0]
        promo=c.execute('SELECT COALESCE(SUM(points),0) FROM ref_redemptions WHERE uid=?',(uid,)).fetchone()[0]
    username=bot.get_me().username
    link='https://t.me/'+username+'?start=ref_'+member['code']
    kb=types.InlineKeyboardMarkup()
    share='https://t.me/share/url?'+urllib.parse.urlencode({'url':link,'text':'PRIVATE DRIVE — индивидуальные поездки по Литве и Европе. Откройте бота по моей ссылке.'})
    kb.add(types.InlineKeyboardButton('Пригласить друга',url=share))
    say(message.chat.id,'🎁 Приглашения и бонусы\n\nВаша ссылка: '+link+'\nПриглашено: '+str(invited)+'\nБонусных баллов: '+str(earned+promo)+'\n\n1 балл за первую завершённую и оплаченную поездку нового друга. Начисления обновляются при открытии этого раздела. Тестовые платежи Stripe не учитываются. Баллы не являются деньгами; автоматическая скидка пока не включена.\nПромокод: /promo КОД',kb)


@bot.message_handler(commands=['ref','bonus'])
def referral_command(message):
    referral_show(message)


@bot.message_handler(commands=['promo'])
def referral_promo(message):
    if message.chat.type != 'private':
        return
    parts=(message.text or '').split()
    if len(parts)!=2 or not re.fullmatch(r'[A-Za-z0-9_-]{3,32}',parts[1]):
        say(message.chat.id,'Введите /promo КОД (3–32 латинские буквы, цифры, _ или -).')
        return
    code=parts[1].upper()
    referral_touch(message.from_user.id)
    with db(USERS_DB) as c:
        c.execute('BEGIN IMMEDIATE')
        p=c.execute('SELECT * FROM ref_promos WHERE code=? AND active=1',(code,)).fetchone()
        used=c.execute('SELECT 1 FROM ref_redemptions WHERE uid=? AND code=?',(message.from_user.id,code)).fetchone()
        count=c.execute('SELECT COUNT(*) FROM ref_redemptions WHERE code=?',(code,)).fetchone()[0]
        if used:
            result='Этот промокод уже использован вами.'
        elif not p or count>=p['max_uses']:
            result='Промокод недействителен или лимит исчерпан.'
        else:
            c.execute('INSERT INTO ref_redemptions VALUES(?,?,?,?)',(message.from_user.id,code,p['points'],now().isoformat()))
            result='Начислено '+str(p['points'])+' бонусных баллов. Баланс: /bonus. Автоматическая скидка пока не включена.'
    say(message.chat.id,result)


@bot.message_handler(commands=['promocreate','promostop'])
def referral_admin_promo(message):
    if message.chat.type!='private' or not is_admin(message.from_user.id):
        return
    p=(message.text or '').split()
    command=p[0].split('@')[0]
    if len(p)>=2 and re.fullmatch(r'[A-Za-z0-9_-]{3,32}',p[1]):
        code=p[1].upper()
        with db(USERS_DB) as c:
            if command=='/promostop' and len(p)==2:
                changed=c.execute('UPDATE ref_promos SET active=0 WHERE code=?',(code,)).rowcount
                say(message.chat.id,'Промокод отключён.' if changed else 'Промокод не найден.')
                return
            if command=='/promocreate' and len(p)==4 and p[2].isdigit() and p[3].isdigit() and 1<=int(p[2])<=1000 and 1<=int(p[3])<=10000:
                cur=c.execute('INSERT OR IGNORE INTO ref_promos(code,points,max_uses) VALUES(?,?,?)',(code,int(p[2]),int(p[3])))
                say(message.chat.id,'Промокод создан: '+code if cur.rowcount else 'Код уже существует; используйте новый код.')
                return
    say(message.chat.id,'Создать: /promocreate КОД БАЛЛЫ ЛИМИТ\nОтключить: /promostop КОД\nБаллы: 1–1000; лимит: 1–10000. Это не денежная скидка.')


def pd_driver_miniapp_entry(message):
    mini_url = os.getenv('MINIAPP_URL', 'https://wilsonpark.pythonanywhere.com').strip()
    if not mini_url.startswith('https://'):
        raise ValueError('MINIAPP_URL must be HTTPS')
    parsed = urllib.parse.urlsplit(mini_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k,v) for k,v in query if k != 'start'] + [('start','driver_taxi_lt')]
    url = urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urllib.parse.urlencode(query),''))
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('🚖 Кабинет и регистрация пилота', web_app=types.WebAppInfo(url)))
    say(message.chat.id,'PRIVATE DRIVE — регистрация пилота и личный кабинет. Откройте приложение:',kb)


@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.type != 'private':
        return
    parts=(message.text or '').split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip() == 'driver_taxi_lt':
        pd_driver_miniapp_entry(message)
        return
    linked=referral_touch(message.from_user.id, parts[1] if len(parts)>1 else '')
    if linked:
        say(message.chat.id, 'Приглашение друга учтено. Добро пожаловать в PRIVATE DRIVE!')
    state_clear(message.from_user.id)
    usr = user_record(message.from_user.id)
    if usr:
        say(message.chat.id, f"👋 PRIVATE DRIVE\nС возвращением, {usr['name']}!", menu())
    else:
        # Registration can be completed inside the Mini App; no duplicate bot questionnaire.
        say(message.chat.id, '👋 PRIVATE DRIVE\nЧтобы заказать поездку, откройте приложение ниже.', menu())
    miniapp_launcher(message.chat.id)


@bot.message_handler(commands=['app'])
def open_mini_app(message):
    if message.chat.type == 'private':
        miniapp_launcher(message.chat.id)


@bot.message_handler(commands=['cancel'])
def cancel(message):
    state_clear(message.from_user.id)
    say(message.chat.id, 'Действие отменено.', menu())


@bot.message_handler(commands=['admin'])
def admin(message):
    if not is_admin(message.from_user.id) or message.chat.type != 'private':
        say(message.chat.id, 'Нет доступа.')
        return
    say(message.chat.id, '🛠️ Админ-панель. Команда /order НОМЕР — карточка заказа.\n'
        '/price НОМЕР СУММА — цена в EUR.\n/crypto НОМЕР BTC|ETH|USDC КОЛИЧЕСТВО — сумма криптооплаты.\n/paylink НОМЕР HTTPS_URL — ссылка оплаты картой.', admin_menu())


@bot.message_handler(commands=['order'])
def order_details(message):
    parts = (message.text or '').split()
    if not is_admin(message.from_user.id) or len(parts) != 2 or not parts[1].isdigit():
        say(message.chat.id, 'Для администратора: /order НОМЕР')
        return
    r = order_find(int(parts[1]))
    say(message.chat.id, order_text(r, True), status_buttons(r['id'])) if r else say(message.chat.id, 'Заказ не найден.')


@bot.message_handler(commands=['price'])
def set_price(message):
    if not is_admin(message.from_user.id):
        return
    say(message.chat.id, 'Устанавливайте цену в административной панели PRIVATE DRIVE: '
        'там проверяются текущий платёж и история корректировок.', miniapp_payment_button())


def status_buttons(order_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    for key, label in [('confirmed', '✅ Принять заказ'), ('canceled', '❌ Отклонить'),
                       ('driving', '🚗 В пути'), ('done', '🏁 Выполнена')]:
        markup.add(types.InlineKeyboardButton(label, callback_data=f'st:{order_id}:{key}'))
    r = order_find(order_id)
    if r and r['payment_method'] == 'Наличные' and r['payment_status'] == 'Ожидается оплата наличными':
        markup.add(types.InlineKeyboardButton('✅ Получил наличные', callback_data=f'cashpaid:{order_id}'))
    return markup


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.startswith('st:'))
def status_change(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, 'Нет доступа')
        return
    bot.answer_callback_query(call.id, 'Управление поездкой доступно в приложении')
    say(call.message.chat.id, 'Изменяйте статус и отменяйте поездки в административной панели PRIVATE DRIVE. '
        'Там учитываются предоплата и возврат пассажиру.', miniapp_payment_button())


@bot.message_handler(content_types=['text', 'contact'])
def messages(message):
    if message.chat.type != 'private':
        return
    uid = message.from_user.id
    txt = (message.text or '').strip()
    if txt in ('❌ Отмена', '🏠 Главное меню'):
        state_clear(uid)
        say(message.chat.id, 'Главное меню', menu())
    elif txt == '🚘 Заказать поездку':
        miniapp_launcher(message.chat.id)
    elif txt == '🎁 Пригласить друга':
        referral_show(message)
    elif txt == '👤 Мой профиль':
        usr = user_record(uid)
        if not usr:
            start_registration(message)
        else:
            say(message.chat.id, f"👤 {usr['name']}\n📱 {usr['phone']}\n🆔 {uid}", menu())
    elif txt == 'ℹ️ Помощь':
        say(message.chat.id, 'Euro Baltic Transfer — персональные трансферы по Литве и Европе.\n'
           'Оформите заявку, получите предварительную цену (если доступен расчёт), '
           'затем дождитесь подтверждения водителем.\n'
           'Доступна оплата наличными водителю, картой по ссылке или USDC/BTC/ETH. '
           'Оплата картой возможна только по подтверждённой ссылке. Отмена: /cancel.\n'
           'Администратор: /admin.', menu())
    elif txt == '📋 Мои заказы':
        with db(ORDERS_DB) as conn:
            rows = conn.execute('SELECT * FROM orders WHERE telegram_id=? ORDER BY id DESC LIMIT 10',
                                (uid,)).fetchall()
        if not rows:
            say(message.chat.id, 'Заказов пока нет.', menu())
        else:
            for r in rows:
                say(message.chat.id, order_text(r), payment_button(r['id']) if r['status'] == 'Подтверждена' and r['price'] else None)
            say(message.chat.id, 'Показаны последние 10 заявок.', menu())
    elif txt == '🚘 Автомобиль и пилот':
        profile = user_record(uid)
        if not profile or not str(profile['name'] or '').strip() or not clean_phone(str(profile['phone'] or '')):
            say(message.chat.id, 'Карточка пилота и документы доступны только после регистрации. Откройте PRIVATE DRIVE и нажмите «Продолжить с Telegram».')
            miniapp_launcher(message.chat.id)
            return
        pic = ROOT / 'pilot_card.png'
        if pic.is_file():
            try:
                with pic.open('rb') as inp:
                    bot.send_photo(message.chat.id, inp)
            except Exception:
                LOG.exception('Pilot card could not be sent')
                say(message.chat.id, 'Карточка временно недоступна.', menu())
        else:
            say(message.chat.id, 'Карточка временно недоступна.', menu())
    elif txt == '📋 Все заказы':
        if not is_admin(uid):
            return
        with db(ORDERS_DB) as conn:
            rows = conn.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 20').fetchall()
        if not rows:
            say(message.chat.id, 'Заказов пока нет.', admin_menu())
        else:
            for r in rows:
                say(message.chat.id, order_text(r, True), status_buttons(r['id']))
    elif txt == '👥 Пользователи':
        if not is_admin(uid):
            return
        with db(USERS_DB) as conn:
            count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        say(message.chat.id, f'👥 Зарегистрировано пользователей: {count}', admin_menu())
    elif state_get(uid):
        process(message)
    else:
        say(message.chat.id, 'Выберите действие в меню или отправьте /start.', menu())


def main():
    initialize()
    referral_initialize()
    identity = bot.get_me()
    LOG.info('Starting @%s', identity.username)
    if not ADMIN_IDS:
        LOG.warning('ADMIN_IDS is empty: no administrator can manage orders')
    if not ORS_API_KEY:
        LOG.warning('ORS_API_KEY absent: quotes will require manual pricing')
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=False, allowed_updates=['message', 'callback_query'],
                         timeout=25, long_polling_timeout=25)


if __name__ == '__main__':
    main()
