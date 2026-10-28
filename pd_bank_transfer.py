"""Manual bank transfers: signed order access and administrator receipts."""
import os
from flask import request, jsonify
from decimal import Decimal
METHOD = 'Банковский перевод'
WAIT = 'Ожидается банковский перевод'
CLAIM = 'Перевод на проверке'
ACCOUNT = dict(recipient=os.getenv('PD_BANK_RECIPIENT',''), iban=os.getenv('PD_PAYSERA_IBAN',''), bank='Paysera LT, UAB', bic='EVIULT2VXXX', address='Pilaitės pr. 16, Vilnius, LT-04352, Lietuva')

ACCOUNTS = {
    'paysera': ACCOUNT,
    'swedbank': dict(recipient=os.getenv('PD_BANK_RECIPIENT',''), iban=os.getenv('PD_SWEDBANK_IBAN',''), bank='Swedbank', bic='', address=''),
}

def register(app, core, auth, cents):
    def schema(c):
        c.execute('''CREATE TABLE IF NOT EXISTS pd_bank_transfers (
            order_id INTEGER PRIMARY KEY, amount_cents INTEGER NOT NULL,
            reference TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
            claimed_at TEXT, received_at TEXT, admin_id INTEGER)''')
        if 'account_id' not in {r[1] for r in c.execute('PRAGMA table_info(pd_bank_transfers)')}:
            c.execute("ALTER TABLE pd_bank_transfers ADD COLUMN account_id TEXT NOT NULL DEFAULT 'paysera'")
    def order(c, oid, uid, admin=False):
        r=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not r or (not (admin and core.is_admin(uid)) and r['telegram_id']!=uid):
            raise PermissionError('Нет доступа')
        return dict(r)
    def pending(r):
        return r['payment_method']==METHOD and r['payment_status'] in (WAIT,CLAIM)
    def notify(fn,*args):
        try: fn(*args)
        except Exception: core.LOG.exception('Bank transfer notification failed')
    with core.db(core.ORDERS_DB) as c: schema(c)

    original=app.view_functions['payment']
    def payment(oid):
        response=original(oid)
        data=response.get_json()
        uid,_=auth()
        with core.db(core.ORDERS_DB) as c: r=order(c,oid,uid,True)
        data['payment_method']=r['payment_method']
        data['bank_transfer_active']=pending(r)
        return jsonify(data)
    app.view_functions['payment']=payment

    @app.before_request
    def pd_bank_prevent_duplicate_payment():
        if request.endpoint in ('select_cash','create_stripe_checkout'):
            uid,_=auth(); oid=(request.view_args or {}).get('oid')
            with core.db(core.ORDERS_DB) as c: r=order(c,oid,uid,True)
            if pending(r):
                raise ValueError('Банковский перевод уже выбран. Смену способа согласуйте с администратором.')

    @app.get('/api/payment/<int:oid>/bank/accounts')
    def pd_bank_accounts(oid):
        uid,_=auth()
        with core.db(core.ORDERS_DB) as c:
            r=order(c,oid,uid,True)
            if r['status']!='Подтверждена' or r['payment_status']=='Оплачено':
                raise ValueError('Проверьте статус заказа')
        return jsonify(accounts=[dict(id=k,bank=v['bank']) for k,v in ACCOUNTS.items()])

    @app.route('/api/payment/<int:oid>/bank',methods=['GET','POST'])
    def pd_bank_details(oid):
        uid,_=auth()
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            r=order(c,oid,uid,True)
            if r['status']!='Подтверждена': raise ValueError('Дождитесь подтверждения поездки')
            amount=cents(r['price'])
            b=c.execute('SELECT * FROM pd_bank_transfers WHERE order_id=?',(oid,)).fetchone()
            if request.method=='POST':
                account_id=(request.get_json(silent=True) or {}).get('account_id', b['account_id'] if b else 'paysera')
                if not isinstance(account_id,str) or account_id not in ACCOUNTS:
                    raise ValueError('Неизвестный банковский счёт')
                if b and b['account_id']!=account_id:
                    raise ValueError('Счёт уже выбран. Смену согласуйте с администратором.')
                if r['payment_status']=='Оплачено': raise ValueError('Заказ уже оплачен')
                if any(r.get(k) for k in ('stripe_session_id','card_payment_url','crypto_currency','crypto_amount','crypto_txid')):
                    raise ValueError('У заказа уже есть онлайн-платёж. Обратитесь к администратору.')
                if r['payment_status'] not in ('Не оплачено','','Ожидается оплата наличными',WAIT,CLAIM):
                    raise ValueError('Другой платёж уже обрабатывается')
                if b and (b['amount_cents']!=amount or b['received_at']): raise ValueError('Проверьте стоимость и статус платежа с администратором')
                if not b:
                    c.execute('INSERT INTO pd_bank_transfers(order_id,amount_cents,reference,created_at,account_id) VALUES(?,?,?,?,?)',(oid,amount,'PD-'+str(oid),core.now().isoformat(),account_id))
                status=CLAIM if b and b['claimed_at'] else WAIT
                c.execute('UPDATE orders SET payment_method=?,payment_status=?,updated_at=? WHERE id=?',(METHOD,status,core.now().isoformat(),oid))
                b=c.execute('SELECT * FROM pd_bank_transfers WHERE order_id=?',(oid,)).fetchone()
            if not b or r['payment_method']!=METHOD and request.method!='POST': raise ValueError('Сначала выберите банковский перевод')
            if b['amount_cents']!=amount: raise ValueError('Стоимость изменилась. Свяжитесь с администратором перед переводом.')
            return jsonify(**ACCOUNTS[b['account_id']],account_id=b['account_id'],order_id=oid,amount=format(Decimal(amount)/100,'.2f'),currency='EUR',reference=b['reference'],claimed=bool(b['claimed_at']),received=bool(b['received_at']))

    @app.post('/api/payment/<int:oid>/bank/claimed')
    def pd_bank_claimed(oid):
        uid,_=auth(); changed=False
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r=order(c,oid,uid)
            b=c.execute('SELECT * FROM pd_bank_transfers WHERE order_id=?',(oid,)).fetchone()
            if not b or not pending(r) or r['status']!='Подтверждена' or b['received_at'] or b['amount_cents']!=cents(r['price']):
                raise ValueError('Проверьте статус заказа и стоимость')
            if not b['claimed_at']:
                now=core.now().isoformat();changed=True
                c.execute('UPDATE pd_bank_transfers SET claimed_at=? WHERE order_id=?',(now,oid))
                c.execute('UPDATE orders SET payment_status=?,updated_at=? WHERE id=?',(CLAIM,now,oid))
        if changed: notify(core.notify_admins,f'🏦 Заказ №{oid}: пассажир сообщил о переводе. Проверьте поступление {Decimal(b["amount_cents"])/100:.2f} EUR с назначением PD-{oid} в {ACCOUNTS[b["account_id"]]["bank"]}. Кнопка пассажира НЕ подтверждает оплату.')
        return jsonify(ok=True,payment_status=CLAIM)

    @app.get('/api/admin/bank-transfers')
    def pd_bank_admin_list():
        uid,_=auth()
        if not core.is_admin(uid): raise PermissionError('Нет доступа')
        with core.db(core.ORDERS_DB) as c:
            rows=c.execute('''SELECT b.*,o.status,o.payment_status,o.payment_method FROM pd_bank_transfers b JOIN orders o ON o.id=b.order_id ORDER BY b.order_id DESC LIMIT 100''').fetchall()
        return jsonify(transfers=[dict(dict(x),bank=ACCOUNTS[x['account_id']]['bank']) for x in rows])

    @app.post('/api/admin/bank-transfers/<int:oid>/received')
    def pd_bank_received(oid):
        uid,_=auth()
        if not core.is_admin(uid): raise PermissionError('Нет доступа')
        d=request.get_json(silent=True) or {}
        if d.get('verified_in_bank') is not True: raise ValueError('Сначала проверьте фактическое поступление в банке')
        received=cents(d.get('amount'));changed=False
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r=order(c,oid,uid,True)
            b=c.execute('SELECT * FROM pd_bank_transfers WHERE order_id=?',(oid,)).fetchone()
            if not b or received!=b['amount_cents'] or received!=cents(r['price']): raise ValueError('Сумма не совпадает с заказом')
            if b['received_at'] and r['payment_status']=='Оплачено': return jsonify(ok=True,replayed=True)
            if r['status'] not in ('Подтверждена','В пути','Выполнена') or not pending(r): raise ValueError('Проверьте статус заказа и способ оплаты')
            now=core.now().isoformat();changed=True
            c.execute('UPDATE pd_bank_transfers SET received_at=?,admin_id=? WHERE order_id=?',(now,uid,oid))
            c.execute("UPDATE orders SET payment_status='Оплачено',updated_at=? WHERE id=?",(now,oid))
        if changed: notify(core.say,r['telegram_id'],f'✅ Заказ №{oid}: банковский перевод получен и подтверждён администратором.')
        return jsonify(ok=True)
