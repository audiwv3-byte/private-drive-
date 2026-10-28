"""Offline smoke tests without Telegram access or third-party packages."""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

class DummyKB:
    def __init__(self, **kwargs): self.buttons=[]
    def row(self,*a): self.buttons.extend(a)
    def add(self,*a): self.buttons.extend(a)
class DummyButton:
    def __init__(self,*a,**k): pass
class DummyBot:
    def __init__(self,*a,**k): self.sent=[]
    def message_handler(self, **kwargs): return lambda f:f
    def callback_query_handler(self,**kwargs): return lambda f:f
    def send_message(self, uid, text, reply_markup=None): self.sent.append((uid,text))
    def answer_callback_query(self,*a,**k): pass
    def send_photo(self,*a,**k): pass
telebot = types.ModuleType('telebot')
telebot.TeleBot = DummyBot
telebot.types = types.SimpleNamespace(ReplyKeyboardMarkup=DummyKB, InlineKeyboardMarkup=DummyKB, KeyboardButton=DummyButton, InlineKeyboardButton=DummyButton)
sys.modules['telebot']=telebot
mod_dotenv=types.ModuleType('dotenv')
mod_dotenv.load_dotenv=lambda *a,**kw:None
sys.modules['dotenv']=mod_dotenv

with tempfile.TemporaryDirectory() as tmp:
    original = Path(__file__).with_name('Euro_Baltic_Transfer.py')
    target=Path(tmp)/'Euro_Baltic_Transfer.py'
    target.write_bytes(original.read_bytes())
    with sqlite3.connect(str(Path(tmp)/'orders.db')) as cn:
        cn.execute('''CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,order_type TEXT NOT NULL,origin TEXT NOT NULL,destination TEXT NOT NULL,trip_date TEXT NOT NULL,trip_time TEXT NOT NULL,passengers INTEGER NOT NULL,luggage TEXT NOT NULL,details TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'Новая',price TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        cn.execute("INSERT INTO orders(telegram_id,order_type,origin,destination,trip_date,trip_time,passengers,luggage) VALUES(1,'В одну сторону','Vilnius','Kaunas','20.10.2026','10:00',2,'Без багажа')")
    with sqlite3.connect(str(Path(tmp)/'users.db')) as cn:
        cn.execute('CREATE TABLE users(telegram_id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        cn.execute("INSERT INTO users (telegram_id,name,phone) VALUES(1,'Test','+37060000000')")
    os.environ['BOT_TOKEN']='123:TEST'
    os.environ['ADMIN_IDS']='999'
    spec=importlib.util.spec_from_file_location('ebt_test', target)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.initialize()
    assert mod.user_record(1)['name']=='Test'
    assert mod.order_find(1)['origin']=='Vilnius'
    assert 'payment_method' in mod.order_find(1).keys()
    mod.state_set(1, {'step':'origin','order_type':'В одну сторону'})
    assert mod.state_get(1)['step']=='origin'
    mod.state_clear(1)
    assert mod.state_get(1) is None
    assert mod.clean_phone('+370 612-34567')=='+37061234567'
    assert mod.clean_phone('bad') is None
    assert mod.quote(100, 120)=='98.00'
    assert mod.quote(100, 120, True)=='196.00'
    state=dict(order_type='В одну сторону',origin='Vilnius',destination='Kaunas',trip_date='31.12.2026',trip_time='10:00',passengers=2,luggage='Без багажа',payment_method='Наличные',details='')
    oid=mod.order_save(1,state)
    assert mod.order_find(oid)['passengers']==2
    assert 'Цена:' in mod.order_text(mod.order_find(oid))
    print('PASS: syntax/import stubs, old DB migration, persistence, validation, estimate, order save')
    # Confirmed booking: only passenger can select cash, only admin can mark receipt.
    from types import SimpleNamespace
    with mod.db(mod.ORDERS_DB) as cn:
        cn.execute("UPDATE orders SET status='Подтверждена',price='153.19' WHERE id=?", (oid,))
    def cb(data, uid):
        return SimpleNamespace(data=data, from_user=SimpleNamespace(id=uid),
                               message=SimpleNamespace(chat=SimpleNamespace(id=uid)), id='test-callback')
    mod.handle_payment(cb(f'pay:{oid}:cash', 1))
    assert mod.order_find(oid)['payment_status'] == 'Ожидается оплата наличными'
    assert mod.order_find(oid)['payment_method'] == 'Наличные'
    mod.admin_cash_received(cb(f'cashpaid:{oid}', 1))
    assert mod.order_find(oid)['payment_status'] == 'Ожидается оплата наличными', 'Passenger cannot confirm cash'
    mod.admin_cash_received(cb(f'cashpaid:{oid}', 999))
    assert mod.order_find(oid)['payment_status'] == 'Оплачено'
    mod.admin_cash_received(cb(f'cashpaid:{oid}', 999))
    assert mod.order_find(oid)['payment_status'] == 'Оплачено', 'Duplicate click must be idempotent'
    assert '💶 Наличными водителю' in original.read_text(encoding='utf-8')
    print('PASS: cash selection, admin-only receipt, duplicate safe')
