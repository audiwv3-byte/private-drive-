"""PRIVATE DRIVE: Stripe TEST adjustment processing; original order price is immutable."""
import os
import time
from decimal import Decimal
import stripe
from flask import request, jsonify

TABLE_SQL = '''CREATE TABLE IF NOT EXISTS pd_stripe_adjustments (
 adjustment_id INTEGER PRIMARY KEY,
 stripe_checkout_session_id TEXT UNIQUE,
 stripe_checkout_url TEXT,
 stripe_payment_intent TEXT,
 stripe_refund_id TEXT UNIQUE,
 updated_at TEXT NOT NULL
)'''

def register(app, core, auth, cents_for_order, stripe_key):
    def require_admin():
        uid, _ = auth()
        if not core.is_admin(uid):
            raise PermissionError('Нет доступа')
        return uid

    @app.post('/api/admin/adjustments/<int:aid>/stripe-checkout')
    def adjustment_checkout(aid):
        require_admin()
        stripe_key()  # test keys only
        if not os.getenv('STRIPE_WEBHOOK_SECRET', '').startswith('whsec_'):
            raise ValueError('Сначала настройте подписанный webhook Stripe Sandbox')
        with core.db(core.ORDERS_DB) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(TABLE_SQL)
            a = conn.execute('SELECT * FROM pd_adjustments WHERE id=?', (aid,)).fetchone()
            if not a or a['kind'] != 'surcharge' or a['status'] not in ('Черновик', 'Ожидает оплаты'):
                raise ValueError('Для доплаты требуется активный черновик')
            order = conn.execute('SELECT * FROM orders WHERE id=?', (a['order_id'],)).fetchone()
            if not order or order['status'] == 'Отменена':
                raise ValueError('Заказ отменён или не найден')
            record = conn.execute('SELECT * FROM pd_stripe_adjustments WHERE adjustment_id=?', (aid,)).fetchone()
            if record and record['stripe_checkout_session_id']:
                return jsonify(ok=True, url=record['stripe_checkout_url'], status=a['status'])
            cents = cents_for_order(a['amount_eur'])
            # Idempotency key makes retries safe if Stripe succeeds before DB commit.
            sess = stripe.checkout.Session.create(
                mode='payment',
                line_items=[{'price_data': {'currency':'eur', 'unit_amount':cents,
                    'product_data': {'name':f'PRIVATE DRIVE — доплата №{aid} за заказ №{a["order_id"]}'}}, 'quantity':1}],
                client_reference_id=f'adjustment:{aid}',
                metadata={'pd_kind':'surcharge','pd_adjustment_id':str(aid),'pd_order_id':str(a['order_id'])},
                success_url='https://wilsonpark.pythonanywhere.com/?adjustment=success',
                cancel_url='https://wilsonpark.pythonanywhere.com/?adjustment=cancel',
                expires_at=int(time.time())+1800,
                idempotency_key=f'pd-test-surcharge-{aid}-v1')
            now = core.now().isoformat()
            conn.execute('INSERT INTO pd_stripe_adjustments(adjustment_id,stripe_checkout_session_id,stripe_checkout_url,updated_at) VALUES(?,?,?,?)',
                         (aid,sess.id,sess.url,now))
            conn.execute("UPDATE pd_adjustments SET status='Ожидает оплаты' WHERE id=?",(aid,))
        return jsonify(ok=True,url=sess.url,status='Ожидает оплаты')

    @app.post('/api/admin/adjustments/<int:aid>/stripe-refund')
    def adjustment_refund(aid):
        require_admin()
        stripe_key()
        with core.db(core.ORDERS_DB) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(TABLE_SQL)
            a=conn.execute('SELECT * FROM pd_adjustments WHERE id=?',(aid,)).fetchone()
            if not a or a['kind']!='refund' or a['status'] not in ('Черновик','Обрабатывается'):
                raise ValueError('Нужен черновик возврата Stripe')
            order=conn.execute('SELECT * FROM orders WHERE id=?',(a['order_id'],)).fetchone()
            if not order or order['payment_status']!='Оплачено' or order['payment_method']!='Онлайн (Stripe)' or not order['stripe_session_id']:
                raise ValueError('Возврат доступен только для оплаченного Stripe-заказа')
            from pd_prepayment_v3 import plain
            session=plain(stripe.checkout.Session.retrieve(order['stripe_session_id']))
            if session.get('payment_status')!='paid' or not session.get('payment_intent'):
                raise ValueError('Stripe не подтвердил платёж')
            payment_intent=session['payment_intent']
            cents=cents_for_order(a['amount_eur'])
            captured=session.get('amount_total')
            if not isinstance(captured,int) or captured < cents or session.get('currency')!='eur':
                raise ValueError('Сумма возврата превышает подтверждённую Stripe-оплату')
            # Include other recorded and pending refunds for the same original order.
            rows=conn.execute("SELECT id,amount_eur FROM pd_adjustments WHERE order_id=? AND kind='refund' AND id<>? AND status IN ('Обрабатывается','Выполнено')",(a['order_id'],aid)).fetchall()
            reserved=sum(cents_for_order(row['amount_eur']) for row in rows)
            if cents+reserved>captured:
                raise ValueError('Сумма возвратов превышает платёж')
            record=conn.execute('SELECT * FROM pd_stripe_adjustments WHERE adjustment_id=?',(aid,)).fetchone()
            if record and record['stripe_refund_id']:
                return jsonify(ok=True,status=a['status'],refund_id=record['stripe_refund_id'])
            now=core.now().isoformat()
            conn.execute("UPDATE pd_adjustments SET status='Обрабатывается' WHERE id=?",(aid,))
            conn.execute('INSERT OR IGNORE INTO pd_stripe_adjustments(adjustment_id,updated_at) VALUES(?,?)',(aid,now))
        # Stripe may succeed before local state update; retry uses the same idempotency key.
        refund=stripe.Refund.create(payment_intent=payment_intent,amount=cents,
                                    metadata={'pd_adjustment_id':str(aid),'pd_order_id':str(a['order_id'])},
                                    idempotency_key=f'pd-test-refund-{aid}-v1')
        with core.db(core.ORDERS_DB) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(TABLE_SQL)
            conn.execute('UPDATE pd_stripe_adjustments SET stripe_payment_intent=?,stripe_refund_id=?,updated_at=? WHERE adjustment_id=?',
                         (payment_intent,refund.id,core.now().isoformat(),aid))
            conn.execute("UPDATE pd_adjustments SET status=? WHERE id=?",('Выполнено' if refund.status=='succeeded' else 'Обрабатывается',aid))
        return jsonify(ok=True,status=refund.status,refund_id=refund.id)

    @app.get('/api/admin/adjustments/stripe-statuses')
    def adjustment_stripe_statuses():
        require_admin()
        with core.db(core.ORDERS_DB) as conn:
            conn.execute(TABLE_SQL)
            rows=conn.execute('SELECT adjustment_id,stripe_checkout_url,stripe_refund_id,updated_at FROM pd_stripe_adjustments ORDER BY updated_at DESC LIMIT 100').fetchall()
        return jsonify(rows=[dict(x) for x in rows])


def handle_checkout_session(core, sess, cents_for_order):
    """Called only AFTER the host endpoint validates the Stripe signature."""
    if (sess.get('metadata') or {}).get('pd_kind') != 'surcharge':
        return None
    meta=sess.get('metadata') or {}
    if sess.get('mode')!='payment' or sess.get('payment_status')!='paid':
        return jsonify(received=True)
    try:
        aid=int(meta['pd_adjustment_id']); oid=int(meta['pd_order_id'])
    except (KeyError,ValueError,TypeError):
        return jsonify(error='Adjustment metadata invalid'),400
    with core.db(core.ORDERS_DB) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(TABLE_SQL)
        row=conn.execute('SELECT * FROM pd_adjustments WHERE id=?',(aid,)).fetchone()
        rec=conn.execute('SELECT * FROM pd_stripe_adjustments WHERE adjustment_id=?',(aid,)).fetchone()
        if (not row or not rec or row['order_id']!=oid or row['kind']!='surcharge'
           or rec['stripe_checkout_session_id']!=sess.get('id')
           or sess.get('currency')!='eur' or sess.get('amount_total')!=cents_for_order(row['amount_eur'])):
            return jsonify(error='Adjustment/session mismatch'),409
        if row['status']=='Оплачено':
            return jsonify(received=True)
        if row['status']!='Ожидает оплаты':
            return jsonify(error='Unexpected adjustment state'),409
        conn.execute('UPDATE pd_adjustments SET status=? WHERE id=?',('Оплачено',aid))
        conn.execute('UPDATE pd_stripe_adjustments SET stripe_payment_intent=?,updated_at=? WHERE adjustment_id=?',
                     (sess.get('payment_intent'),core.now().isoformat(),aid))
    return jsonify(received=True)
