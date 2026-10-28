"""Pilot assignments with server-side authorization for every request."""
from flask import request,jsonify

def ensure(core):
 with core.db(core.ORDERS_DB) as c:
  c.execute('''CREATE TABLE IF NOT EXISTS pd_pilot_assignments (order_id INTEGER PRIMARY KEY,pilot_id INTEGER NOT NULL,assigned_by INTEGER NOT NULL,assigned_at TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS pd_pilot_assignment_log (id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,pilot_id INTEGER,admin_id INTEGER NOT NULL,changed_at TEXT NOT NULL)''')

def register(app,core,auth):
 ensure(core)
 def approved(uid):
  with core.db(core.USERS_DB) as c:
   row=c.execute("SELECT status FROM pd_driver_applications WHERE telegram_id=?",(uid,)).fetchone()
  return bool(row and row['status']=='approved')
 prev=app.view_functions['me']
 def me_driver():
  uid,_=auth();response=prev();data=response.get_json();data['pilot_access']=approved(uid);return jsonify(data)
 app.view_functions['me']=me_driver
 @app.get('/api/driver/work')
 def work():
  uid,_=auth()
  if not approved(uid):raise PermissionError('Доступ пилота отсутствует')
  with core.db(core.ORDERS_DB) as c:
   rows=c.execute('''SELECT o.id,o.telegram_id,o.origin,o.destination,o.stop_address,o.order_type,o.trip_date,o.trip_time,o.status,o.price,o.payment_method,o.payment_status,o.passengers,o.luggage,o.details FROM orders o JOIN pd_pilot_assignments a ON a.order_id=o.id WHERE a.pilot_id=? ORDER BY o.id DESC LIMIT 100''',(uid,)).fetchall()
  with core.db(core.USERS_DB) as c:
   result=[]
   for r in rows:
    item=dict(r);customer=c.execute('SELECT name,phone FROM users WHERE telegram_id=?',(item.pop('telegram_id'),)).fetchone();item['customer']=dict(customer) if customer else {};result.append(item)
  return jsonify(orders=result)
 @app.get('/api/admin/pilot-assignments')
 def assignments():
  uid,_=auth()
  if not core.is_admin(uid):raise PermissionError('Нет доступа')
  with core.db(core.USERS_DB) as c:pilots=[dict(r) for r in c.execute("SELECT telegram_id,name,vehicle,plate FROM pd_driver_applications WHERE status='approved' ORDER BY name LIMIT 200")]
  with core.db(core.ORDERS_DB) as c:rows=[dict(r) for r in c.execute('SELECT order_id,pilot_id FROM pd_pilot_assignments')]
  return jsonify(pilots=pilots,assignments=rows)
 @app.post('/api/admin/pilot-assignments/<int:oid>')
 def assign(oid):
  uid,_=auth()
  if not core.is_admin(uid):raise PermissionError('Нет доступа')
  body=request.get_json(silent=True) or {};pilot=body.get('pilot_id')
  if pilot is not None and (type(pilot) is not int or not approved(pilot)):raise ValueError('Выберите одобренного пилота')
  with core.db(core.ORDERS_DB) as c:
   c.execute('BEGIN IMMEDIATE');order=c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()
   if not order:return jsonify(error='Заказ не найден'),404
   if order['status'] not in ('Новая','Подтверждена'):raise ValueError('Назначение доступно для новых и подтверждённых заказов')
   old=c.execute('SELECT pilot_id FROM pd_pilot_assignments WHERE order_id=?',(oid,)).fetchone()
   if (old['pilot_id'] if old else None)==pilot:return jsonify(ok=True)
   now=core.now().isoformat()
   if pilot is None:c.execute('DELETE FROM pd_pilot_assignments WHERE order_id=?',(oid,))
   else:c.execute('INSERT INTO pd_pilot_assignments VALUES(?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET pilot_id=excluded.pilot_id,assigned_by=excluded.assigned_by,assigned_at=excluded.assigned_at',(oid,pilot,uid,now))
   c.execute('INSERT INTO pd_pilot_assignment_log(order_id,pilot_id,admin_id,changed_at) VALUES(?,?,?,?)',(oid,pilot,uid,now))
  return jsonify(ok=True)
 @app.post('/api/driver/work/<int:oid>/status')
 def status(oid):
  uid,_=auth()
  if not approved(uid):raise PermissionError('Доступ пилота отсутствует')
  d=request.get_json(silent=True) or {};target=d.get('status');allowed={'В пути':'Подтверждена','Выполнена':'В пути'}
  if target not in allowed:raise ValueError('Недопустимый статус')
  with core.db(core.ORDERS_DB) as c:
   c.execute('ATTACH DATABASE ? AS pilot_users',(str(core.USERS_DB),));c.execute('BEGIN IMMEDIATE')
   still_approved=c.execute("SELECT 1 FROM pilot_users.pd_driver_applications WHERE telegram_id=? AND status='approved'",(uid,)).fetchone()
   if not still_approved:raise PermissionError('Доступ пилота отсутствует')
   r=c.execute('SELECT o.status,o.telegram_id,o.payment_status FROM orders o JOIN pd_pilot_assignments a ON a.order_id=o.id WHERE o.id=? AND a.pilot_id=?',(oid,uid)).fetchone()
   if not r:return jsonify(error='Заказ не найден'),404
   if r['status']!=allowed[target]:raise ValueError('Статус заказа уже изменился')
   if target=='В пути' and r['payment_status']!='Оплачено':raise ValueError('Дождитесь подтверждённой оплаты перед началом поездки')
   c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(target,core.now().isoformat(),oid))
  try:
   text=f'🚘 Заказ №{oid}: статус «{target}».'
   if target=='Выполнена':text+='\nПоездка окончена. Спасибо за поездку! Откройте приложение, чтобы оценить водителя.'
   core.say(r['telegram_id'],text)
  except Exception:core.LOG.exception('Pilot status notification failed')
  return jsonify(ok=True)
