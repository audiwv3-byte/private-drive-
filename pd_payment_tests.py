"""Provider-mocked regressions for consent, refund boundaries, races and charge limits."""
import hashlib,hmac,json,os,time
from unittest.mock import patch
from datetime import timedelta

def run(server,core,client,call,signed,check):
    import pd_prepayment_v3 as mod
    os.environ.update(PD_PAYMENT_MODE='test',STRIPE_SECRET_KEY='sk_test_release_fixture',STRIPE_WEBHOOK_SECRET='whsec_release_fixture')
    core.save_user(999,'Test Admin','+37060000001')
    body={'accept_terms':True,'policy_version':mod.POLICY,'extra_limit':'0'}
    clock=int(time.time())
    def order(price='100.00',uid=999):
        st=dict(order_type='В одну сторону',origin='Vilnius',destination='Trakai',trip_date=(core.now()+timedelta(days=2)).strftime('%d.%m.%Y'),trip_time='14:00',passengers=2,luggage='Без багажа',details='',payment_method='Наличными',price=price)
        oid=core.order_save(uid,st)
        with core.db(core.ORDERS_DB) as c:c.execute("UPDATE orders SET status='Подтверждена' WHERE id=?",(oid,))
        return oid
    def session(oid,amount=10000):return dict(id='cs_test_'+str(oid),url='https://checkout.stripe.com/c/pay/'+str(oid),livemode=False,mode='payment',amount_total=amount,currency='eur',metadata={'pd_kind':'prepayment','order_id':str(oid)},payment_status='paid',payment_intent='pi_test_'+str(oid),customer='cus_test_'+str(oid))
    def event(oid,kind='checkout.session.completed',obj=None,created=None,eid=None,live=False):
        data={'id':eid or 'evt_'+str(oid)+'_'+kind,'type':kind,'created':created or clock,'livemode':live,'data':{'object':obj or session(oid)}}
        raw=json.dumps(data).encode();now=str(int(time.time()));sig=hmac.new(os.environ['STRIPE_WEBHOOK_SECRET'].encode(),now.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return client.post('/api/stripe/webhook',data=raw,headers={'Stripe-Signature':'t='+now+',v1='+sig},content_type='application/json')
    def checkout(oid,consent=False):
        payload=body|({'extra_limit':'10.00','extra_consent':True} if consent else {})
        with patch.object(mod.stripe.checkout.Session,'create',return_value=session(oid)) as create:
            check(call(f'/api/payment/{oid}/checkout',payload,uid=999),200)
            check(call(f'/api/payment/{oid}/checkout',payload,uid=999),200)
            assert create.call_count==1
            assert ('payment_intent_data' in create.call_args.kwargs)==consent
    def prepay(oid,consent=False):checkout(oid,consent);check(event(oid),200)
    def refund(oid,amount,status='pending'):
        return dict(id='re_test_'+str(oid),payment_intent='pi_test_'+str(oid),amount=amount,currency='eur',status=status,metadata={'pd_kind':'cancellation','order_id':str(oid)})
    def cancellation(oid,delta=0,amount=10000,driver=False):
        with patch.object(mod.time,'time',return_value=clock+delta),patch.object(mod.stripe.Refund,'create',return_value=refund(oid,amount)) as create:
            path=('/api/admin/orders/' if driver else '/api/orders/')+str(oid)+'/cancel'
            result=check(call(path,{'confirm':True,'reason':'Test cancellation'},uid=999),200)
            assert create.call_count==1
            assert create.call_args.kwargs['amount']==amount
            assert result['cancellation']['state']=='pending'
            check(call(path,{'confirm':True,'reason':'Test cancellation'},uid=999),200)
            assert create.call_count==1
        return result
    # Real-mode and consent gates fail closed without invoking Stripe.
    oid=order()
    with patch.object(mod.stripe.checkout.Session,'create') as create:
        with patch.dict(os.environ,{'PD_PAYMENT_MODE':'disabled'}):check(call(f'/api/payment/{oid}/checkout',body,uid=999),503)
        with patch.dict(os.environ,{'PD_PAYMENT_MODE':'live','STRIPE_SECRET_KEY':'sk_live_fixture'}):check(call(f'/api/payment/{oid}/checkout',body,uid=999),503)
        check(call(f'/api/payment/{oid}/checkout',body,uid=101),503)
        check(call(f'/api/payment/{oid}/checkout',{},uid=999),400)
        check(call(f'/api/payment/{oid}/checkout',body|{'extra_limit':'10'},uid=999),400)
        assert not create.called
    interrupted=order()
    with patch.object(mod.stripe.checkout.Session,'create',side_effect=mod.stripe.error.APIConnectionError('fixture')) as create:
        check(call(f'/api/payment/{interrupted}/checkout',body,uid=999),400)
        first_params=create.call_args.kwargs
    with core.db(core.ORDERS_DB) as c:
        assert c.execute('SELECT state FROM pd_prepayments WHERE order_id=?',(interrupted,)).fetchone()[0]=='creating'
    check(call(f'/api/payment/{interrupted}/bank',{},uid=999),400)
    with patch.object(mod.stripe.checkout.Session,'create',return_value=session(interrupted)) as create:
        check(call(f'/api/payment/{interrupted}/checkout',body,uid=999),200)
        assert create.call_args.kwargs==first_params
    print('PASS Checkout interruption: durable ledger, identical retry parameters and payment-method lock')
    checkout(oid)
    assert core.order_find(oid)['payment_status']!='Оплачено'
    wrong=session(oid);wrong['amount_total']=999
    check(event(oid,obj=wrong),409)
    check(client.post('/api/stripe/webhook',data='{}',content_type='application/json'),400)
    check(event(oid),200);check(event(oid),200)
    assert core.order_find(oid)['payment_status']=='Оплачено'
    check(call('/api/admin/status',{'id':oid,'status':'Отменена'},uid=999),400)
    check(call(f'/api/orders/{oid}/cancel',{'confirm':True,'reason':'Test'},uid=101),401)
    print('PASS prepayment gates: mode, account role, terms, save-card consent, provider idempotency, signature, exact amount and duplicate webhooks')
    # Exactly five minutes is free; one second later uses the snapshotted 20%.
    cancellation(oid,300)
    assert core.order_find(oid)['status']=='Отменена'
    with core.db(core.ORDERS_DB) as c:assert c.execute('SELECT refund_cents FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()[0]==10000
    obj=refund(oid,10000,'succeeded')
    with core.db(core.ORDERS_DB) as c:
        c.execute("UPDATE pd_prepayments SET mode='live' WHERE order_id=?",(oid,))
        c.execute("UPDATE pd_cancellations SET mode='live' WHERE order_id=?",(oid,))
    with patch.dict(os.environ,{'STRIPE_SECRET_KEY':'sk_live_fixture'}):
        check(event(oid,'refund.updated',obj,clock+301,eid='evt_refund_succeeded',live=True),200)
    with core.db(core.ORDERS_DB) as c:
        c.execute("UPDATE pd_prepayments SET mode='test' WHERE order_id=?",(oid,))
        c.execute("UPDATE pd_cancellations SET mode='test' WHERE order_id=?",(oid,))
    obj['status']='failed'
    check(event(oid,'refund.failed',obj,clock+300,eid='evt_refund_old_failure'),200)
    with core.db(core.ORDERS_DB) as c:assert c.execute('SELECT state FROM pd_cancellations WHERE order_id=?',(oid,)).fetchone()[0]=='succeeded'
    late=order();prepay(late);cancellation(late,301,2000)
    driver=order();prepay(driver);cancellation(driver,3600,10000,True)
    print('PASS cancellation boundaries: 300 seconds full refund, 301 seconds 20%, driver cancellation full refund; pending is distinct from succeeded and late events cannot reverse success')
    # Payment can arrive after cancellation, so the event handler must arrange a full refund.
    race=order();checkout(race)
    check(call(f'/api/orders/{race}/cancel',{'confirm':True,'reason':'Test'},uid=999),200)
    with patch.object(mod.stripe.Refund,'create',return_value=refund(race,10000)) as create:
        check(event(race,created=clock+400),200)
        assert create.call_args.kwargs['amount']==10000
    assert core.order_find(race)['status']=='Отменена'
    retry=order();prepay(retry)
    with patch.object(mod.stripe.Refund,'create',side_effect=TimeoutError('fixture')) as create:
        check(call(f'/api/orders/{retry}/cancel',{'confirm':True,'reason':'Test'},uid=999),202)
        key=create.call_args.kwargs['idempotency_key']
    with patch.object(mod.stripe.Refund,'create',return_value=refund(retry,10000)) as create:
        check(call(f'/api/orders/{retry}/cancel',{'confirm':True,'reason':'Test'},uid=999),200)
        assert key==create.call_args.kwargs['idempotency_key']
    bank=order(uid=101)
    check(call(f'/api/payment/{bank}/bank',{}),200);check(call(f'/api/payment/{bank}/bank/claimed',{}),200)
    with patch.object(mod.stripe.Refund,'create') as create:
        result=check(call(f'/api/orders/{bank}/cancel',{'confirm':True,'reason':'Test'}),200)
        assert result['cancellation']['manual_review'] and not create.called
    print('PASS payment/cancellation race, full late-arriving-payment refund, timeout retry with same provider key, and bank transfers requiring manual reconciliation')
    # Extra charges require saved-card consent, completed trip, exact agreed amount and a cumulative cap.
    extra=order();prepay(extra,True)
    def adjustment(oid,amount):return check(call('/api/admin/adjustments',{'id':oid,'kind':'surcharge','amount':amount,'reason':'Test agreed change'},uid=999),200)['adjustment_id']
    aid=adjustment(extra,'5.00')
    with patch.object(mod.stripe.PaymentIntent,'create') as create:
        check(call(f'/api/admin/adjustments/{aid}/saved-card',{},uid=999),400);assert not create.called
    with core.db(core.ORDERS_DB) as c:c.execute("UPDATE orders SET status='Выполнена' WHERE id=?",(extra,))
    original=dict(status='succeeded',customer='cus_test_'+str(extra),amount_received=10000,payment_method='pm_fixture')
    intent=dict(id='pi_extra_'+str(aid),amount=500,currency='eur',livemode=False,status='succeeded')
    with patch.object(mod.stripe.PaymentIntent,'retrieve',return_value=original),patch.object(mod.stripe.PaymentIntent,'create',return_value=intent) as create:
        check(call(f'/api/admin/adjustments/{aid}/saved-card',{},uid=999),200)
        assert check(call(f'/api/admin/adjustments/{aid}/saved-card',{},uid=999),200)['replayed']
        assert create.call_count==1
        assert create.call_args.kwargs['off_session'] is True
        next_aid=adjustment(extra,'6.00')
        check(call(f'/api/admin/adjustments/{next_aid}/saved-card',{},uid=999),400)
        assert create.call_count==1
    assert core.order_find(extra)['price']=='100.00'
    no_consent=order();prepay(no_consent)
    with core.db(core.ORDERS_DB) as c:c.execute("UPDATE orders SET status='Выполнена' WHERE id=?",(no_consent,))
    aid=adjustment(no_consent,'1.00')
    with patch.object(mod.stripe.PaymentIntent,'create') as create:
        check(call(f'/api/admin/adjustments/{aid}/saved-card',{},uid=999),400);assert not create.called
    check(call('/api/admin/payment-readiness',uid=999),200)
    check(call('/api/admin/payment-readiness',uid=101),401)
    print('PASS extra charges: consent, trip completed, saved method ownership, duplicate safety, cumulative limit and immutable original fare; readiness is admin-only')
    os.environ['PD_PAYMENT_MODE']='disabled'
