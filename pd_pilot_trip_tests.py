"""Regression tests for pilot stop timer, passenger route consent and pilot isolation."""
from datetime import timedelta

def run(server, core, call, check):
    pilot_id,passenger_id=556,101
    core.save_user(pilot_id,'Test Pilot','+37060000556')
    with core.db(core.USERS_DB) as c:
        c.execute('''INSERT INTO pd_driver_applications
         (telegram_id,name,phone,city,vehicle,vehicle_year,plate,seats,status,created_at,updated_at)
         VALUES(?,?,?,?,?,?,?,?,'approved',?,?)''',
         (pilot_id,'Test Pilot','+37060000556','Vilnius','Toyota',2020,'TEST556',4,
          core.now().isoformat(),core.now().isoformat()))
    booking={
        'order_type':'В одну сторону','origin':'Vilnius','destination':'Trakai',
        'trip_date':(core.now()+timedelta(days=2)).strftime('%d.%m.%Y'),
        'trip_time':'14:00','passengers':2,'luggage':'Без багажа',
        'details':'Runtime test','payment_method':'Наличными','price':'80.00'
    }
    oid=core.order_save(passenger_id,booking)
    with core.db(core.ORDERS_DB) as c:
        c.execute("UPDATE orders SET status='Подтверждена',payment_status='Оплачено' WHERE id=?",(oid,))
        c.execute('INSERT INTO pd_pilot_assignments(order_id,pilot_id,assigned_by,assigned_at) VALUES(?,?,?,?)',
                  (oid,pilot_id,999,core.now().isoformat()))
    path=f'/api/trip/{oid}'
    assert check(call(path,uid=pilot_id),200)['role']=='pilot'
    check(call(path,uid=102),403)
    check(call(path+'/action',{'action':'pause'},uid=passenger_id),403)
    check(call(path+'/route-change',{'destination':'54.69,25.29'},uid=passenger_id),403)
    check(call(path+'/action',{'action':'arrive'},uid=pilot_id),200)
    check(call(path+'/action',{'action':'start'},uid=pilot_id),200)
    paused=check(call(path+'/action',{'action':'pause'},uid=pilot_id),200)
    assert paused['stop_active'] and paused['stop_count']==1
    again=check(call(path+'/action',{'action':'pause'},uid=pilot_id),200)
    assert again['stop_count']==1
    check(call(path+'/action',{'action':'finish'},uid=pilot_id),400)
    assert check(call(path,uid=passenger_id),200)['stop_active']
    resumed=check(call(path+'/action',{'action':'resume'},uid=pilot_id),200)
    assert not resumed['stop_active'] and resumed['stop_count']==1
    check(call(path+'/action',{'action':'resume'},uid=pilot_id),200)
    proposed=check(call(path+'/route-change',{'destination':'54.69,25.29'},uid=pilot_id),200)
    assert proposed['route_pending']['destination']=='54.69,25.29'
    check(call(path+'/route-change',{'destination':'54.70,25.30'},uid=pilot_id),400)
    check(call(path+'/route-change/decision',{'accept':True},uid=102),403)
    accepted=check(call(path+'/route-change/decision',{'accept':True},uid=passenger_id),200)
    assert accepted['route_destination']=='54.69,25.29'
    assert accepted['route_pending'] is None
    check(call(path+'/route-change/decision',{'accept':True},uid=passenger_id),400)
    check(call(path+'/route-change',{'destination':'54.70,25.30'},uid=pilot_id),200)
    rejected=check(call(path+'/route-change/decision',{'accept':False},uid=passenger_id),200)
    assert rejected['route_destination']=='54.69,25.29'
    finished=check(call(path+'/action',{'action':'finish'},uid=pilot_id),200)
    assert finished['status']=='Выполнена'
    assert finished['drive_seconds']>=0 and finished['stop_count']==1
    assert finished['final_cents']==8000
    assert core.order_find(oid)['destination']=='Trakai'
    check(call(path+'/action',{'action':'pause'},uid=pilot_id),400)
    admin=check(call('/api/admin/trip/'+str(oid),uid=999),200)
    assert len(admin['route_history'])==2 and admin['stop_count']==1
    print('PASS pilot stops: persisted, idempotent, bounded by trip, completion guarded')
    print('PASS route changes: pilot-only proposal, passenger acceptance/rejection, no automatic fare change')
