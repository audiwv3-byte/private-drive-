"""Prepayment and cancellation ledger. Disabled by default; test mode is admin-only.
No card details are stored. Real mode requires reviewed settings and live credentials.
"""
import json,os,time
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import stripe
from flask import request,jsonify,send_file,Response
POLICY='PD-PREPAY-20261027-v1'
FREE_SECONDS=300
LATE_REFUND_PERCENT=20
PAID='Оплачено'

def plain(value):
    if isinstance(value, dict):return {k:plain(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):return [plain(v) for v in value]
    if hasattr(value,'to_dict_recursive'):return plain(value.to_dict_recursive())
    if hasattr(value,'to_dict'):return plain(value.to_dict())
    return value

def mode():return os.getenv('PD_PAYMENT_MODE','disabled').strip()
def is_live():return mode()=='live'
def configure():
    m=mode();key=os.getenv('STRIPE_SECRET_KEY','').strip()
    if m not in ('test','live') or not key.startswith('sk_live_' if m=='live' else 'sk_test_'):
        raise ValueError('Оплата картой ещё не подключена')
    if not os.getenv('STRIPE_WEBHOOK_SECRET','').startswith('whsec_'):
        raise ValueError('Подтверждение платежей ещё не настроено')
    if m=='live' and os.getenv('PD_LIVE_PAYMENTS_APPROVED')!='1':
        raise ValueError('Реальные платежи ещё не активированы')
    if m=='live' and os.getenv('PD_CANCELLATION_POLICY_APPROVED')!='1':
        raise ValueError('Условия оплаты и возвратов ещё не подтверждены')
    if m=='live' and os.getenv('PD_LIVE_WEBHOOK_EVENTS_VERIFIED')!='1':
        raise ValueError('Уведомления о платежах и возвратах ещё не проверены')
    stripe.api_key=key
    stripe.max_network_retries=1
    return m

def schema(core):
    with core.db(core.ORDERS_DB) as c:
        import pd_stripe_adjustments
        c.execute(pd_stripe_adjustments.TABLE_SQL)
        c.executescript('''
        CREATE TABLE IF NOT EXISTS pd_adjustments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('surcharge','refund')),amount_eur TEXT NOT NULL,
          reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Черновик',
          admin_telegram_id INTEGER NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pd_prepayments (
          order_id INTEGER PRIMARY KEY,amount_cents INTEGER NOT NULL,mode TEXT NOT NULL,
          session_id TEXT UNIQUE,checkout_url TEXT,payment_intent TEXT UNIQUE,customer_id TEXT,
          state TEXT NOT NULL,paid_at INTEGER,agreed_at INTEGER NOT NULL,policy_version TEXT NOT NULL,
          free_seconds INTEGER NOT NULL,late_refund_percent INTEGER NOT NULL,
          extra_limit_cents INTEGER NOT NULL DEFAULT 0,extra_consent INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pd_cancellations (
          order_id INTEGER PRIMARY KEY,requested_by INTEGER NOT NULL,requested_at INTEGER NOT NULL,
          refund_cents INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,refund_id TEXT UNIQUE,
          reason TEXT NOT NULL,policy_version TEXT NOT NULL,mode TEXT NOT NULL,
          last_event_at INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pd_payment_events (
          event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,received_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS pd_extra_charges (
          adjustment_id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,
          mode TEXT NOT NULL,state TEXT NOT NULL,intent_id TEXT UNIQUE,last_event_at INTEGER NOT NULL DEFAULT 0);
        ''')

def register(app,core,auth,cents):
    schema(core)
    def owner(c,oid,uid,admin=False):
        row=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not row or (row['telegram_id']!=uid and not (admin and core.is_admin(uid))):
            raise PermissionError('Нет доступа')
        return row
    def admin():
        uid,_=auth()
        if not core.is_admin(uid):raise PermissionError('Нет доступа')
        return uid
    def access():
        uid,_=auth();m=configure()
        if m=='test' and not core.is_admin(uid):raise PermissionError('Тестовые платежи доступны только администратору')
        return uid,m
    def available(uid):
        try:configure();return is_live() or core.is_admin(uid)
        except ValueError:return False
    def other_refunds(c,oid):
        rows=c.execute("SELECT amount_eur FROM pd_adjustments WHERE order_id=? AND kind='refund' AND status!='Отменено'",(oid,)).fetchall()
        return sum(cents(x['amount_eur']) for x in rows)
    def cancellation_info(row,pre):
        if not row:return None
        return dict(requested=True,state=row['state'],refund_amount=format(Decimal(row['refund_cents'])/100,'.2f'),
                    refund_final=row['state']=='succeeded',manual_review=row['state']=='manual_review')
    def payment_info(oid):
        uid,_=auth()
        with core.db(core.ORDERS_DB) as c:
            r=owner(c,oid,uid,True)
            p=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
            cancel=c.execute('SELECT * FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()
        return dict(card_enabled=available(uid),test_mode=mode()=='test',policy_version=POLICY,
                    free_cancellation_seconds=FREE_SECONDS,late_refund_percent=LATE_REFUND_PERCENT,
                    prepayment_state=p['state'] if p else None,
                    paid_at=p['paid_at'] if p else None,
                    free_cancellation_until=p['paid_at']+p['free_seconds'] if p and p['paid_at'] else None,
                    cancellation=cancellation_info(cancel,p),can_cancel=r['status'] in ('Новая','Подтверждена'))
    previous_payment=app.view_functions['payment']
    def enriched_payment(oid):
        response=previous_payment(oid)
        if isinstance(response,tuple):return response
        data=response.get_json();data.update(payment_info(oid));return jsonify(data)
    app.view_functions['payment']=enriched_payment
    @app.get('/api/payment/<int:oid>/prepayment-status')
    def pd_prepayment_status(oid):return jsonify(payment_info(oid))

    def checkout(oid):
        uid,m=access();body=request.get_json(silent=True) or {}
        if body.get('accept_terms') is not True or body.get('policy_version')!=POLICY:
            raise ValueError('Ознакомьтесь с условиями предоплаты и отмены')
        extra=body.get('extra_limit','0')
        extra_cents=0 if str(extra).strip() in ('','0','0.00') else cents(extra)
        if extra_cents and body.get('extra_consent') is not True:
            raise ValueError('Для последующей доплаты нужно отдельное согласие')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r=owner(c,oid,uid)
            if r['status']!='Подтверждена':raise ValueError('Дождитесь подтверждения поездки')
            if r['payment_status'] not in ('Не оплачено','','Ожидается оплата наличными'):
                raise ValueError('Оплата уже получена или обрабатывается')
            if any(r[k] for k in ('crypto_currency','crypto_amount','crypto_txid')):
                raise ValueError('Для заказа уже выбран другой платёж')
            amount=cents(r['price'])
            existing=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
            if existing:
                if existing['amount_cents']!=amount or existing['extra_limit_cents']!=extra_cents or existing['mode']!=m:
                    raise ValueError('Условия уже созданного платежа изменять нельзя. Обратитесь к администратору.')
                if existing['state']=='checkout' and existing['checkout_url']:
                    return jsonify(url=existing['checkout_url'],test_mode=m=='test',replayed=True)
                if existing['state']!='creating' or int(time.time())-existing['agreed_at']>72000:
                    raise ValueError('Проверьте актуальный статус платежа с администратором')
            else:
                if r['stripe_session_id'] or r['card_payment_url']:raise ValueError('У заказа уже есть платёжная сессия')
                # Commit the operation before contacting Stripe. A network failure must not erase it.
                c.execute('''INSERT INTO pd_prepayments(order_id,amount_cents,mode,state,agreed_at,policy_version,free_seconds,late_refund_percent,extra_limit_cents,extra_consent)
                 VALUES(?,?,?,'creating',?,?,?,?,?,?)''',(oid,amount,m,int(time.time()),POLICY,FREE_SECONDS,LATE_REFUND_PERCENT,extra_cents,int(extra_cents>0)))
        params=dict(mode='payment',payment_method_types=['card'],customer_creation='always',
          line_items=[{'price_data':{'currency':'eur','unit_amount':amount,'product_data':{'name':f'PRIVATE DRIVE · 100% prepayment · #{oid}'}},'quantity':1}],
          client_reference_id=str(oid),metadata={'pd_kind':'prepayment','order_id':str(oid),'policy_version':POLICY},
          success_url='https://wilsonpark.pythonanywhere.com/?payment=return',cancel_url='https://wilsonpark.pythonanywhere.com/?payment=cancel',
          idempotency_key=f'pd-{m}-prepay-{oid}-{amount}-{extra_cents}-v3')
        if extra_cents:params['payment_intent_data']={'setup_future_usage':'off_session'}
        try:sess=plain(stripe.checkout.Session.create(**params))
        except stripe.error.StripeError:
            raise ValueError('Платёжный сервис временно недоступен. Повторите попытку: повторное списание защищено.') from None
        if bool(sess.get('livemode'))!=(m=='live') or not str(sess.get('url','')).startswith('https://checkout.stripe.com/'):
            raise ValueError('Платёжный сервис вернул неверный режим или адрес')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r=owner(c,oid,uid)
            current=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
            if current['session_id'] and current['session_id']!=sess['id']:raise ValueError('Требуется сверка платежа')
            c.execute("UPDATE pd_prepayments SET session_id=?,checkout_url=?,state=CASE WHEN state='creating' THEN 'checkout' ELSE state END WHERE order_id=?",(sess['id'],sess['url'],oid))
            c.execute("UPDATE orders SET stripe_session_id=?,stripe_amount_cents=?,card_payment_url=?,payment_method='Онлайн (Stripe)',updated_at=? WHERE id=?",(sess['id'],amount,sess['url'],core.now().isoformat(),oid))
        if r['status']=='Отменена':raise ValueError('Поездка уже отменена. Не оплачивайте её.')
        return jsonify(url=sess['url'],test_mode=m=='test')
    app.view_functions['create_stripe_checkout']=checkout

    def refund_cancel(oid):
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            cancel=c.execute('SELECT * FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()
            p=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
            if not cancel or cancel['state'] not in ('refund_requested','processing','retry','pending','requires_action'):return
            configure()
            if not p or not p['payment_intent'] or p['mode']!=mode():raise ValueError('Требуется сверка платежа')
            if cancel['refund_cents']+other_refunds(c,oid)>p['amount_cents']:raise ValueError('По заказу уже есть другая заявка на возврат')
            c.execute("UPDATE pd_cancellations SET state='processing' WHERE order_id=?",(oid,))
        try:
            if cancel['refund_id']:refund=stripe.Refund.retrieve(cancel['refund_id'])
            else:refund=stripe.Refund.create(payment_intent=p['payment_intent'],amount=cancel['refund_cents'],reason='requested_by_customer',
                  metadata={'pd_kind':'cancellation','order_id':str(oid)},idempotency_key=f'pd-{p["mode"]}-cancel-{oid}-v3')
            refund=plain(refund)
            if refund.get('payment_intent')!=p['payment_intent'] or refund.get('amount')!=cancel['refund_cents'] or refund.get('currency')!='eur' or ('livemode' in refund and bool(refund['livemode'])!=(p['mode']=='live')):
                raise ValueError('Несоответствие возврата')
            state=refund.get('status');state=state if state in ('succeeded','pending','failed','canceled','requires_action') else 'pending'
            with core.db(core.ORDERS_DB) as c:
                c.execute("UPDATE pd_cancellations SET refund_id=?,state=? WHERE order_id=? AND state!='succeeded'",(refund['id'],state,oid))
        except Exception:
            with core.db(core.ORDERS_DB) as c:c.execute("UPDATE pd_cancellations SET state='retry' WHERE order_id=? AND refund_id IS NULL AND state='processing'",(oid,))
            raise
    def cancel_order(oid,uid,body,driver=False):
        if body.get('confirm') is not True:raise ValueError('Подтвердите отмену поездки')
        reason=body.get('reason','Изменились планы')
        if not isinstance(reason,str) or not 2<=len(reason.strip())<=300:raise ValueError('Укажите причину отмены')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');r=owner(c,oid,uid,driver)
            previous=c.execute('SELECT * FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()
            if not previous:
                if r['status'] not in ('Новая','Подтверждена'):raise ValueError('Поездку уже нельзя отменить в приложении. Свяжитесь с нами.')
                now=int(time.time());p=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
                state='unpaid';refund=0
                if p and p['state']=='paid':
                    if p['mode']!=mode():raise ValueError('Требуется сверка платежа')
                    free=driver or now-p['paid_at']<=p['free_seconds']
                    refund=p['amount_cents'] if free else int((Decimal(p['amount_cents'])*p['late_refund_percent']/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                    if other_refunds(c,oid):raise ValueError('По заказу уже оформляется возврат. Свяжитесь с нами.')
                    state='refund_requested'
                elif p and p['state'] in ('checkout','creating'):state='awaiting_payment_check'
                elif r['payment_status'] not in ('Не оплачено','','Ожидается оплата наличными','Ожидается банковский перевод'):
                    state='manual_review'
                c.execute('INSERT INTO pd_cancellations(order_id,requested_by,requested_at,refund_cents,state,reason,policy_version,mode) VALUES(?,?,?,?,?,?,?,?)',(oid,uid,now,refund,state,reason.strip(),POLICY,p['mode'] if p else 'manual'))
                c.execute("UPDATE orders SET status='Отменена',updated_at=? WHERE id=?",(core.now().isoformat(),oid))
        with core.db(core.ORDERS_DB) as c:cancel=c.execute('SELECT * FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()
        try:
            if cancel['state'] in ('refund_requested','processing','retry'):refund_cancel(oid)
        except Exception:
            return jsonify(ok=True,cancelled=True,refund_pending=True,notice='Поездка отменена. Статус возврата проверяется; не оформляйте повторный платёж.'),202
        return jsonify(ok=True,cancelled=True,**payment_info(oid))
    @app.post('/api/orders/<int:oid>/cancel')
    def pd_passenger_cancel(oid):
        uid,_=auth()
        return cancel_order(oid,uid,request.get_json(silent=True) or {})
    @app.post('/api/admin/orders/<int:oid>/cancel')
    def pd_driver_cancel(oid):
        uid=admin()
        return cancel_order(oid,uid,request.get_json(silent=True) or {},driver=True)

    @app.before_request
    def pd_payment_mutation_guards():
        if request.method!='POST':return
        body=request.get_json(silent=True) or {}
        if request.endpoint in ('admin_price_change_pd','pd_admin_final_price','select_cash','pd_bank_details'):
            oid=(request.view_args or {}).get('oid') if request.endpoint in ('select_cash','pd_bank_details') else body.get('id')
            with core.db(core.ORDERS_DB) as c:p=c.execute('SELECT 1 FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
            if p:raise ValueError('Карточный платёж уже создаётся или создан. Смену оплаты и цены нужно сверить с администратором.')
        if request.endpoint in ('admin_status','status'):
            oid=body.get('id') if request.endpoint=='admin_status' else (request.view_args or {}).get('oid')
            with core.db(core.ORDERS_DB) as c:
                p=c.execute('SELECT state FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
            if p and body.get('status')=='Отменена':raise ValueError('Используйте отмену с расчётом возврата')
            if p and body.get('status')=='В пути' and p['state']!='paid':raise ValueError('Дождитесь подтверждённой предоплаты')
        if request.endpoint=='pd_admin_adjustments' and body.get('kind')=='refund':
            with core.db(core.ORDERS_DB) as c:
                cancel=c.execute('SELECT 1 FROM pd_cancellations WHERE order_id=?',(body.get('id'),)).fetchone()
            if cancel:raise ValueError('По заказу уже оформлена отмена. Используйте журнал возвратов.')
        if request.endpoint in ('adjustment_checkout','adjustment_refund','pd_cancel_adjustment'):
            aid=(request.view_args or {}).get('aid',(request.view_args or {}).get('adjustment_id'))
            with core.db(core.ORDERS_DB) as c:
                row=c.execute('SELECT 1 FROM pd_extra_charges WHERE adjustment_id=?',(aid,)).fetchone()
                a=c.execute('SELECT order_id FROM pd_adjustments WHERE id=?',(aid,)).fetchone()
                cancel=c.execute('SELECT 1 FROM pd_cancellations WHERE order_id=?',(a['order_id'],)).fetchone() if a else None
            if row:raise ValueError('По доплате уже выполняется списание. Проверьте его статус.')
            if cancel:raise ValueError('По заказу уже оформляется возврат при отмене')

    @app.get('/api/admin/payment-readiness')
    def pd_payment_readiness():
        admin();key=os.getenv('STRIPE_SECRET_KEY','')
        with core.db(core.ORDERS_DB) as c:
            has_settings=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pd_invoice_settings'").fetchone()
            row=c.execute('SELECT data FROM pd_invoice_settings WHERE singleton=1').fetchone() if has_settings else None
            settings=json.loads(row['data']) if row else {}
            pending=c.execute("SELECT COUNT(*) FROM pd_cancellations WHERE state NOT IN ('succeeded','unpaid','canceled')").fetchone()[0]
        return jsonify(mode=mode(),test_key_present=key.startswith('sk_test_'),live_key_present=key.startswith('sk_live_'),
          webhook_configured=os.getenv('STRIPE_WEBHOOK_SECRET','').startswith('whsec_'),live_approved=os.getenv('PD_LIVE_PAYMENTS_APPROVED')=='1',
          live_webhook_events_verified=os.getenv('PD_LIVE_WEBHOOK_EVENTS_VERIFIED')=='1',
          cancellation_policy_approved=os.getenv('PD_CANCELLATION_POLICY_APPROVED')=='1',invoice_settings_saved=bool(row),
          seller_address_present=bool(settings.get('seller_address')),tax_mode_confirmed=settings.get('tax_mode') in ('svs','standard21','manual'),
          pending_refunds=pending,policy_version=POLICY)
    @app.get('/api/admin/cancellations')
    def pd_cancellations_list():
        admin()
        with core.db(core.ORDERS_DB) as c:rows=c.execute('SELECT order_id,requested_at,refund_cents,state,reason FROM pd_cancellations ORDER BY requested_at DESC LIMIT 100').fetchall()
        return jsonify(cancellations=[dict(r) for r in rows])
    @app.post('/api/admin/cancellations/<int:oid>/retry')
    def pd_cancellation_retry(oid):
        admin();refund_cancel(oid);return jsonify(ok=True)

    # Signed Stripe notifications are the source of truth, never a browser return URL.
    old_webhook=app.view_functions['stripe_webhook']
    def webhook():
        key=os.getenv('STRIPE_SECRET_KEY','').strip();secret=os.getenv('STRIPE_WEBHOOK_SECRET','').strip()
        if not secret.startswith('whsec_'):return jsonify(error='Webhook not configured'),503
        try:event=plain(stripe.Webhook.construct_event(request.get_data(),request.headers.get('Stripe-Signature',''),secret))
        except (ValueError,stripe.error.SignatureVerificationError):return jsonify(error='Invalid signature'),400
        kind=event.get('type');obj=(event.get('data') or {}).get('object') or {};meta=obj.get('metadata') or {}
        if meta.get('pd_kind') not in ('prepayment','cancellation','extra_charge'):
            return old_webhook()
        if not key.startswith('sk_live_' if event.get('livemode') else 'sk_test_') or ('livemode' in obj and bool(obj['livemode'])!=bool(event.get('livemode'))):
            return jsonify(error='Payment mode mismatch'),409
        retry_cancel=None
        try:
            with core.db(core.ORDERS_DB) as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('SELECT 1 FROM pd_payment_events WHERE event_id=?',(event['id'],)).fetchone():
                    # A retry must also resume a refund interrupted after the ledger commit.
                    if meta.get('pd_kind')=='prepayment':retry_cancel=int(meta['order_id'])
                else:
                    oid=int(meta['order_id'])
                    p=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(oid,)).fetchone()
                    if not p or (p['mode']=='live')!=bool(event['livemode']):raise ValueError('Unknown payment')
                    if meta['pd_kind']=='prepayment':
                        if obj.get('id')!=p['session_id'] or obj.get('amount_total')!=p['amount_cents'] or obj.get('currency')!='eur':raise ValueError('Session mismatch')
                        if kind in ('checkout.session.completed','checkout.session.async_payment_succeeded') and obj.get('payment_status')=='paid':
                            if obj.get('mode')!='payment' or not isinstance(obj.get('payment_intent'),str):raise ValueError('Invalid payment')
                            paid_at=p['paid_at'] or int(event['created'])
                            c.execute("UPDATE pd_prepayments SET state='paid',payment_intent=?,customer_id=?,paid_at=? WHERE order_id=?",(obj['payment_intent'],obj.get('customer'),paid_at,oid))
                            c.execute("UPDATE orders SET payment_status='Оплачено',payment_method='Онлайн (Stripe)',updated_at=? WHERE id=?",(core.now().isoformat(),oid))
                            cancel=c.execute('SELECT * FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()
                            if cancel and cancel['state'] in ('unpaid','awaiting_payment_check'):
                                c.execute("UPDATE pd_cancellations SET state='refund_requested',refund_cents=? WHERE order_id=?",(p['amount_cents'],oid));retry_cancel=oid
                        elif kind in ('checkout.session.expired','checkout.session.async_payment_failed') and p['state']!='paid':
                            c.execute("UPDATE pd_prepayments SET state='expired' WHERE order_id=?",(oid,))
                            c.execute("UPDATE pd_cancellations SET state='unpaid' WHERE order_id=? AND state='awaiting_payment_check'",(oid,))
                    elif meta['pd_kind']=='cancellation' and kind in ('refund.created','refund.updated','refund.failed'):
                        cancel=c.execute('SELECT * FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()
                        if (not cancel or obj.get('payment_intent')!=p['payment_intent'] or obj.get('amount')!=cancel['refund_cents'] or obj.get('currency')!='eur'
                            or cancel['refund_id'] and cancel['refund_id']!=obj.get('id')):raise ValueError('Refund mismatch')
                        state=obj.get('status')
                        if state not in ('pending','requires_action','succeeded','failed','canceled'):raise ValueError('Invalid refund state')
                        if int(event['created'])>=cancel['last_event_at'] and cancel['state']!='succeeded':
                            c.execute('UPDATE pd_cancellations SET refund_id=?,state=?,last_event_at=? WHERE order_id=?',(obj['id'],state,int(event['created']),oid))
                    elif meta['pd_kind']=='extra_charge':
                        aid=int(meta['adjustment_id']);row=c.execute('SELECT * FROM pd_extra_charges WHERE adjustment_id=? AND order_id=?',(aid,oid)).fetchone()
                        if not row or obj.get('id')!=row['intent_id'] or obj.get('amount')!=row['amount_cents'] or obj.get('currency')!='eur':raise ValueError('Extra charge mismatch')
                        if kind=='payment_intent.succeeded' and obj.get('status')=='succeeded':
                            c.execute("UPDATE pd_extra_charges SET state='succeeded' WHERE adjustment_id=?",(aid,))
                            c.execute("UPDATE pd_adjustments SET status='Оплачено' WHERE id=?",(aid,))
                    c.execute('INSERT INTO pd_payment_events VALUES(?,?,?)',(event['id'],kind,int(time.time())))
        except (ValueError,KeyError,TypeError):return jsonify(error='Payment event mismatch'),409
        if retry_cancel:
            try:refund_cancel(retry_cancel)
            except Exception:return jsonify(error='Refund retry required'),503
        return jsonify(received=True)
    app.view_functions['stripe_webhook']=webhook

    @app.post('/api/admin/adjustments/<int:aid>/saved-card')
    def pd_extra_saved_card(aid):
        uid,m=access()
        if not core.is_admin(uid):raise PermissionError('Нет доступа')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE')
            a=c.execute('SELECT * FROM pd_adjustments WHERE id=?',(aid,)).fetchone()
            if not a or a['kind']!='surcharge':raise ValueError('Нужна согласованная доплата')
            old=c.execute('SELECT * FROM pd_extra_charges WHERE adjustment_id=?',(aid,)).fetchone()
            if old and old['state']=='succeeded':return jsonify(ok=True,state='succeeded',replayed=True)
            if a['status'] not in ('Черновик','Обрабатывается'):raise ValueError('Нужна согласованная доплата')
            r=owner(c,a['order_id'],uid,True);p=c.execute('SELECT * FROM pd_prepayments WHERE order_id=?',(a['order_id'],)).fetchone()
            if r['status']!='Выполнена' or not p or p['state']!='paid' or not p['extra_consent'] or p['mode']!=m or not p['customer_id']:
                raise ValueError('Нужно завершить поездку и получить согласие пассажира на доплату')
            amount=cents(a['amount_eur'])
            rows=c.execute("SELECT amount_cents FROM pd_extra_charges WHERE order_id=? AND adjustment_id<>? AND state NOT IN ('failed','canceled')",(r['id'],aid)).fetchall()
            if amount+sum(x['amount_cents'] for x in rows)>p['extra_limit_cents']:raise ValueError('Доплата превышает согласованный пассажиром лимит')
            if old and old['amount_cents']!=amount:raise ValueError('Сумма уже зафиксирована')
            if old and old['state']=='succeeded':return jsonify(ok=True,state='succeeded',replayed=True)
            other=c.execute('SELECT 1 FROM pd_stripe_adjustments WHERE adjustment_id=?',(aid,)).fetchone()
            if other:raise ValueError('По доплате уже создан другой платёж')
            c.execute("INSERT OR IGNORE INTO pd_extra_charges(adjustment_id,order_id,amount_cents,mode,state) VALUES(?,?,?,?,'processing')",(aid,r['id'],amount,m))
            c.execute("UPDATE pd_adjustments SET status='Обрабатывается' WHERE id=?",(aid,))
        original=plain(stripe.PaymentIntent.retrieve(p['payment_intent']))
        if original.get('status')!='succeeded' or original.get('customer')!=p['customer_id'] or original.get('amount_received')!=p['amount_cents'] or not original.get('payment_method'):
            raise ValueError('Проверьте исходный платёж')
        try:
            intent=stripe.PaymentIntent.create(amount=amount,currency='eur',customer=p['customer_id'],payment_method=original['payment_method'],
              off_session=True,confirm=True,metadata={'pd_kind':'extra_charge','order_id':str(r['id']),'adjustment_id':str(aid)},idempotency_key=f'pd-{m}-extra-{aid}-v3')
        except stripe.error.CardError:
            with core.db(core.ORDERS_DB) as c:c.execute("UPDATE pd_extra_charges SET state='requires_action' WHERE adjustment_id=?",(aid,))
            return jsonify(ok=False,state='requires_action',notice='Банк требует участия пассажира. Автоматическое списание не подтверждено.'),409
        intent=plain(intent)
        if intent.get('amount')!=amount or intent.get('currency')!='eur' or bool(intent.get('livemode'))!=(m=='live'):
            raise ValueError('Несоответствие доплаты')
        state=intent.get('status','processing')
        with core.db(core.ORDERS_DB) as c:
            c.execute('UPDATE pd_extra_charges SET intent_id=?,state=? WHERE adjustment_id=?',(intent['id'],state,aid))
            if state=='succeeded':c.execute("UPDATE pd_adjustments SET status='Оплачено' WHERE id=?",(aid,))
        return jsonify(ok=state=='succeeded',state=state)
    @app.get('/assets/pd-prepayment-v3.js')
    def pd_prepayment_script():return send_file(Path(__file__).with_suffix('.js'),mimetype='text/javascript',max_age=0)
    @app.get('/payment-terms')
    def pd_payment_terms():
        lang=request.args.get('lang','ru')
        text={
          'ru':('Предоплата и отмена поездки',[
            'Тестовая редакция. Реальные карточные платежи и удержания пока не активированы. Условия требуют проверки применимости перед коммерческим запуском.',
            'После подтверждения поездки водителем пассажир оплачивает 100% подтверждённой цены на защищённой странице Stripe. Само подтверждение водителем не списывает деньги с новой карты без действий пассажира.',
            'Первые 5 минут отсчитываются от подтверждённой успешной предоплаты. При отмене пассажиром в этот срок расчёт возврата составляет 100%, позднее — 20%. При отмене водителем возвращается 100%. Если платёж поступил уже после отмены, оформляется полный возврат.',
            'Окончательное состояние возврата подтверждает Stripe. Статус «ожидается» не означает, что деньги уже вернулись на карту. Возврат направляется на исходный способ оплаты; срок зачисления зависит от платёжного сервиса и банка.',
            'Сохранение способа оплаты для доплаты необязательно и требует отдельного согласия. Пассажир указывает максимальную суммарную доплату в EUR для этой поездки. Доплата возможна только после завершения поездки, с указанной причиной корректировки и в пределах остатка согласованного лимита. Исходная оплата хранится отдельно. Банк может потребовать дополнительное подтверждение пассажира.',
            'Приложение не хранит полный номер карты и CVV. При банковском переводе проверка поступления и возврат выполняются отдельно; нажатие «Я оплатил» не подтверждает поступление денег.',
            'Контакты: eurobaltictransfer@gmail.com · Telegram @PrivatDraiv. Версия условий: '+POLICY]),
          'en':('Prepayment and cancellation',[
            'Test edition. Real card payments and cancellation fees are not active. Applicability must be reviewed before commercial launch.',
            'After the driver confirms the trip, the passenger pays 100% of the confirmed fare on Stripe. Driver confirmation alone does not debit a new card without passenger action.',
            'The 5-minute window starts after confirmed successful prepayment. Passenger cancellation within this window gives a calculated 100% refund; later, 20%. Driver cancellations receive 100%. Payments arriving after cancellation are refunded in full.',
            'Stripe confirms the final refund state. Pending does not mean the money has arrived in the card account. Refunds use the original payment method; arrival time depends on Stripe and the bank.',
            'Saving a payment method for an extra charge is optional and requires separate consent. The passenger specifies a maximum cumulative amount in EUR for this trip. An extra charge is possible only after trip completion, with a recorded adjustment reason and within the remaining authorized limit. The initial payment remains a separate record. The bank may require passenger authentication.',
            'The app does not store full card numbers or CVVs. Bank transfers need separate payment and refund reconciliation. Selecting “I paid” is not confirmation that money has arrived.',
            'Contact: eurobaltictransfer@gmail.com · Telegram @PrivatDraiv. Terms version: '+POLICY]),
          'lt':('Išankstinis mokėjimas ir atšaukimas',[
            'Testinė redakcija. Realūs mokėjimai kortele ir atšaukimo mokesčiai neaktyvūs. Prieš komercinį paleidimą reikia patikrinti sąlygų taikymą.',
            'Vairuotojui patvirtinus kelionę keleivis Stripe puslapyje sumoka 100% patvirtintos kainos. Vien vairuotojo patvirtinimas nenuskaito pinigų iš naujos kortelės be keleivio veiksmų.',
            '5 minučių terminas prasideda po patvirtinto sėkmingo išankstinio mokėjimo. Keleiviui atšaukus per šį laiką apskaičiuojamas 100% grąžinimas, vėliau — 20%. Vairuotojui atšaukus grąžinama 100%. Po atšaukimo gautas mokėjimas grąžinamas visas.',
            'Galutinę grąžinimo būseną patvirtina Stripe. Laukianti būsena nereiškia, kad pinigai jau pasiekė kortelės sąskaitą. Pinigai grąžinami į pradinį mokėjimo būdą; terminas priklauso nuo Stripe ir banko.',
            'Mokėjimo būdo išsaugojimas priemokai neprivalomas ir reikalauja atskiro sutikimo. Keleivis nurodo didžiausią bendrą priemoką EUR šiai kelionei. Priemoka galima tik baigus kelionę, užfiksavus koregavimo priežastį ir neviršijant likusio patvirtinto limito. Pradinis mokėjimas saugomas atskirai. Bankas gali paprašyti keleivio patvirtinimo.',
            'Programėlė nesaugo visų kortelės numerių ir CVV. Banko pavedimai ir jų grąžinimai tikrinami atskirai. Paspaudimas „Sumokėjau“ nepatvirtina pinigų gavimo.',
            'Kontaktai: eurobaltictransfer@gmail.com · Telegram @PrivatDraiv. Sąlygų versija: '+POLICY])}
        title,paragraphs=text.get(lang,text['ru'])
        if is_live() and os.getenv('PD_CANCELLATION_POLICY_APPROVED')=='1':
            paragraphs=list(paragraphs)
            paragraphs[0]={'ru':'Условия предоплаты, отмены и согласованной доплаты для этой поездки.',
                          'en':'Prepayment, cancellation and authorized extra-charge terms for this trip.',
                          'lt':'Šios kelionės išankstinio mokėjimo, atšaukimo ir patvirtintos priemokos sąlygos.'}.get(lang,'Условия оплаты поездки.')
        from html import escape
        content='<!doctype html><html lang="'+escape(lang if lang in text else 'ru')+'"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PRIVATE DRIVE</title><style>body{max-width:760px;margin:32px auto;padding:24px;font:17px/1.6 system-ui;background:#111;color:#eee}h1,a{color:#e8c47c}</style><h1>'+escape(title)+'</h1>'+''.join('<p>'+escape(p)+'</p>' for p in paragraphs)+'<p><a href="/?lang='+escape(lang if lang in text else 'ru')+'">PRIVATE DRIVE</a></p></html>'
        return Response(content,mimetype='text/html',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
    app.config['PD_PREPAYMENT_AVAILABLE']=available
