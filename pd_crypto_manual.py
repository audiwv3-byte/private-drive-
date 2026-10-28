"""Order-scoped crypto instructions; receipts are verified manually by admin."""
import re
from decimal import Decimal, InvalidOperation
from flask import request, jsonify

NETWORKS = {'BTC': 'Bitcoin Mainnet', 'ETH': 'Ethereum Mainnet', 'USDC': 'Ethereum Mainnet (ERC-20)'}
PRECISION = {'BTC': 8, 'ETH': 18, 'USDC': 6}
WAIT = 'Ожидается криптоперевод'
CLAIM = 'Криптоперевод на проверке'

def valid_address(currency, address):
    if currency in ('ETH', 'USDC'):
        return bool(re.fullmatch(r'0x[0-9a-fA-F]{40}', address)) and int(address[2:],16)!=0
    return bool(re.fullmatch(r'(?:bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})',address))

def quantity(currency, value):
    if not isinstance(currency,str) or currency not in PRECISION: raise ValueError('Выберите BTC, ETH или USDC')
    try: d=Decimal(str(value).replace(',','.'))
    except InvalidOperation: raise ValueError('Укажите точную сумму в криптовалюте')
    if not d.is_finite() or d<=0 or d>Decimal('1000000000') or d.as_tuple().exponent < -PRECISION[currency]:
        raise ValueError('Некорректная сумма или слишком много знаков после запятой')
    return format(d,'f')

def tx_hash(currency, value):
    value=str(value or '').strip()
    pattern=r'[0-9a-fA-F]{64}' if currency=='BTC' else r'0x[0-9a-fA-F]{64}'
    if not re.fullmatch(pattern,value): raise ValueError('Укажите полный TXID транзакции выбранной сети')
    return value.lower()

def register(app,core,auth,cents):
    with core.db(core.ORDERS_DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pd_crypto_payments (
            order_id INTEGER PRIMARY KEY, currency TEXT NOT NULL, network TEXT NOT NULL,
            address TEXT NOT NULL, amount TEXT NOT NULL, price_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL, assigned_by INTEGER NOT NULL,
            txid TEXT, claimed_at TEXT, received_at TEXT, verified_by INTEGER,
            UNIQUE(currency,txid))''')
    def available():
        return [k for k in NETWORKS if valid_address(k,core.CRYPTO_ADDRESSES.get(k,''))]
    def read(c,oid,uid,admin=False):
        row=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not row or not (row['telegram_id']==uid or admin and core.is_admin(uid)):
            raise PermissionError('Нет доступа')
        p=c.execute('SELECT * FROM pd_crypto_payments WHERE order_id=?',(oid,)).fetchone()
        return dict(row),dict(p) if p else None
    def admin_user():
        uid,_=auth()
        if not core.is_admin(uid): raise PermissionError('Нет доступа')
        return uid
    def check(r,p):
        if r['status']!='Подтверждена': raise ValueError('Дождитесь подтверждения поездки')
        if p and p['price_cents']!=cents(r['price']): raise ValueError('Стоимость изменилась. Не переводите деньги; свяжитесь с администратором.')
    def notify(fn,*args):
        try: fn(*args)
        except Exception: core.LOG.exception('Crypto receipt notification failed')
    original=app.view_functions['payment']
    def payment(oid):
        response=original(oid);data=response.get_json();uid,_=auth()
        with core.db(core.ORDERS_DB) as c:r,p=read(c,oid,uid,True)
        if p:
            active=r['status']=='Подтверждена' and p['price_cents']==cents(r['price'])
            data.update(crypto_currency=p['currency'],crypto_amount=p['amount'] if active else '',
                        addresses={k:p['address'] if active and k==p['currency'] else '' for k in NETWORKS})
        return jsonify(data)
    app.view_functions['payment']=payment

    @app.get('/api/tips/options')
    def pd_tip_options():
        uid,_=auth()
        from pd_bank_transfer import ACCOUNTS
        return jsonify(reference='TIP-PD-'+str(uid),banks=[dict(id=k,**v) for k,v in ACCOUNTS.items()],
                       crypto=[dict(currency=k,network=NETWORKS[k],address=core.CRYPTO_ADDRESSES[k]) for k in available()])

    @app.get('/api/payment/<int:oid>/crypto/details')
    def pd_crypto_details(oid):
        uid,_=auth()
        with core.db(core.ORDERS_DB) as c:r,p=read(c,oid,uid,True)
        check(r,p)
        if r['payment_status']=='Оплачено':raise ValueError('Заказ уже оплачен')
        safe={k:p[k] for k in ('currency','network','address','amount','txid','claimed_at')} if p else None
        return jsonify(assigned=bool(p),payment=safe,currencies=available())

    @app.post('/api/payment/<int:oid>/crypto/claimed')
    def pd_crypto_claimed(oid):
        uid,_=auth();data=request.get_json(silent=True) or {};changed=False
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r,p=read(c,oid,uid)
            check(r,p)
            if not p or p['received_at'] or r['payment_status'] not in (WAIT,CLAIM) or r['payment_method']!='Криптовалюта':
                raise ValueError('Проверьте способ оплаты и статус заказа')
            txid=tx_hash(p['currency'],data.get('txid'))
            other=c.execute('SELECT order_id FROM pd_crypto_payments WHERE currency=? AND txid=?',(p['currency'],txid)).fetchone()
            if other and other['order_id']!=oid:raise ValueError('Этот TXID уже используется для другого заказа')
            if p['txid'] and p['txid']!=txid:raise ValueError('TXID уже сохранён. Для исправления обратитесь к администратору.')
            if not p['claimed_at']:
                now=core.now().isoformat();changed=True
                c.execute('UPDATE pd_crypto_payments SET txid=?,claimed_at=? WHERE order_id=?',(txid,now,oid))
                c.execute('UPDATE orders SET crypto_txid=?,payment_status=?,updated_at=? WHERE id=?',(txid,CLAIM,now,oid))
        if changed:notify(core.notify_admins,f'₿ Заказ №{oid}: заявлен криптоперевод. Проверьте сеть, адрес, токен, сумму и подтверждения в блокчейне. Нажатие пассажира не подтверждает оплату.')
        return jsonify(ok=True,payment_status=CLAIM)

    @app.route('/api/admin/crypto-payment/<int:oid>',methods=['GET','POST'])
    def pd_crypto_assign(oid):
        uid=admin_user();data=request.get_json(silent=True) or {}
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r,p=read(c,oid,uid,True)
            if request.method=='GET':return jsonify(order_id=oid,price=r['price'],payment=p,currencies=available())
            check(r,p)
            if r['payment_status'] not in ('Не оплачено','',WAIT,CLAIM):raise ValueError('Другой платёж уже обрабатывается')
            cur=data.get('currency');amount=quantity(cur,data.get('amount'))
            if p:
                if p['currency']==cur and Decimal(p['amount'])==Decimal(amount) and not p['received_at']:return jsonify(ok=True,replayed=True)
                raise ValueError('Реквизиты криптоплатежа уже зафиксированы')
            if any(r.get(k) for k in ('stripe_session_id','card_payment_url','crypto_currency','crypto_amount','crypto_txid')) or r.get('stripe_amount_cents') is not None:
                raise ValueError('Для заказа уже назначен другой платёж')
            if r['payment_method']=='Банковский перевод':raise ValueError('Для заказа уже выбран банковский перевод')
            if cur not in available():raise ValueError('Адрес для этой валюты не настроен')
            address=core.CRYPTO_ADDRESSES[cur];now=core.now().isoformat()
            c.execute('INSERT INTO pd_crypto_payments(order_id,currency,network,address,amount,price_cents,created_at,assigned_by) VALUES(?,?,?,?,?,?,?,?)',
                      (oid,cur,NETWORKS[cur],address,amount,cents(r['price']),now,uid))
            c.execute('UPDATE orders SET payment_method=?,payment_status=?,crypto_currency=?,crypto_amount=?,updated_at=? WHERE id=?',('Криптовалюта',WAIT,cur,amount,now,oid))
        return jsonify(ok=True)

    @app.post('/api/admin/crypto-payment/<int:oid>/received')
    def pd_crypto_received(oid):
        uid=admin_user();data=request.get_json(silent=True) or {};changed=False
        if data.get('verified_on_chain') is not True:raise ValueError('Проверьте поступление в нужной сети и кошельке')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r,p=read(c,oid,uid,True)
            if not p:raise ValueError('Криптоплатёж не назначен')
            txid=tx_hash(p['currency'],data.get('txid'));amount=quantity(p['currency'],data.get('amount'))
            if txid!=p['txid'] or Decimal(amount)!=Decimal(p['amount']):raise ValueError('TXID или сумма не совпадает')
            if p['received_at'] and r['payment_status']=='Оплачено':return jsonify(ok=True,replayed=True)
            if r['status'] not in ('Подтверждена','В пути','Выполнена') or r['payment_status']!=CLAIM or r['payment_method']!='Криптовалюта' or p['price_cents']!=cents(r['price']):
                raise ValueError('Проверьте статус заказа и платежа')
            now=core.now().isoformat();changed=True
            c.execute('UPDATE pd_crypto_payments SET received_at=?,verified_by=? WHERE order_id=?',(now,uid,oid))
            c.execute("UPDATE orders SET payment_status='Оплачено',updated_at=? WHERE id=?",(now,oid))
        if changed:notify(core.say,r['telegram_id'],f'✅ Заказ №{oid}: криптоперевод проверен и подтверждён администратором.')
        return jsonify(ok=True)
