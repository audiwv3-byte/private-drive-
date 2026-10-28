"""Admin order console: private search, guarded edits and immutable audit history."""
import hashlib
import json
import re
from datetime import datetime
from flask import request, jsonify

STATUSES=('Новая','Подтверждена','В пути','Выполнена','Отменена')
EDITABLE={'origin','destination','stop_address','trip_date','trip_time','passengers','luggage','details'}

def register(app,core,auth):
    with core.db(core.ORDERS_DB) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS pd_admin_order_notes_v4(
          order_id INTEGER PRIMARY KEY,note TEXT NOT NULL,updated_at TEXT NOT NULL,admin_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS pd_admin_order_audit_v4(
          id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,admin_id INTEGER NOT NULL,
          action TEXT NOT NULL,reason TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,created_at TEXT NOT NULL);''')
    def admin():
        uid,_=auth()
        if not core.is_admin(uid):raise PermissionError('Только для администратора')
        return uid
    def table(c,name):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())
    def snapshot(c,oid):
        r=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not r:raise ValueError('Заказ не найден')
        data=dict(r)
        assigned=c.execute('SELECT pilot_id FROM pd_pilot_assignments WHERE order_id=?',(oid,)).fetchone()
        note=c.execute('SELECT note FROM pd_admin_order_notes_v4 WHERE order_id=?',(oid,)).fetchone()
        data['pilot_id']=assigned['pilot_id'] if assigned else None
        data['admin_note']=note['note'] if note else ''
        return data
    def revision(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    def locks(c,r):
        reasons=[]
        if r['status'] not in ('Новая','Подтверждена'):reasons.append('Поездка началась, завершена или отменена')
        if r['payment_status'] not in ('Не оплачено','','Ожидается оплата наличными'):reasons.append('Оплата получена или обрабатывается')
        if any(r.get(k) for k in ('stripe_session_id','card_payment_url','crypto_currency','crypto_amount','crypto_txid')):reasons.append('Платёж уже создан')
        for name in ('pd_booking_capture_v4','pd_prepayments','pd_invoices'):
            if table(c,name) and c.execute('SELECT 1 FROM '+name+' WHERE order_id=? LIMIT 1',(r['id'],)).fetchone():
                reasons.append('Создан платёж или выпущен счёт');break
        if table(c,'pd_trip_runtime_v4'):
            t=c.execute('SELECT arrived_at,started_at FROM pd_trip_runtime_v4 WHERE order_id=?',(r['id'],)).fetchone()
            if t and (t['arrived_at'] or t['started_at']):reasons.append('Пилот уже прибыл или начал поездку')
        return list(dict.fromkeys(reasons))
    def audit(c,oid,uid,action,reason,before,after):
        c.execute('INSERT INTO pd_admin_order_audit_v4(order_id,admin_id,action,reason,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)',
            (oid,uid,action,reason,json.dumps(before,ensure_ascii=False,default=str),json.dumps(after,ensure_ascii=False,default=str),core.now().isoformat()))
    def date(value):
        if not isinstance(value,str):raise ValueError('Укажите дату')
        try:return datetime.strptime(value,'%d.%m.%Y').date()
        except ValueError:raise ValueError('Дата должна быть в формате ДД.ММ.ГГГГ') from None

    @app.get('/api/admin/console/orders')
    def pd_admin_console_orders():
        admin();args=request.args;q=str(args.get('q','')).strip()[:120];status=args.get('status','all')
        if status not in ('all','unpaid','unassigned','waiting',*STATUSES):raise ValueError('Неизвестный фильтр')
        try:limit=max(1,min(50,int(args.get('limit',25))));before=int(args.get('before',0))
        except (TypeError,ValueError):raise ValueError('Некорректная страница') from None
        if before<0:raise ValueError('Некорректная страница')
        where=[];params=[]
        if before:where.append('o.id<?');params.append(before)
        if status in STATUSES:where.append('o.status=?');params.append(status)
        elif status=='unpaid':where.append("o.payment_status!='Оплачено' AND o.status NOT IN ('Отменена','Выполнена')")
        elif status=='unassigned':where.append("a.pilot_id IS NULL AND o.status NOT IN ('Отменена','Выполнена')")
        elif status=='waiting':where.append("t.arrived_at IS NOT NULL AND t.started_at IS NULL AND o.status='Подтверждена'")
        if q:
            where.append("(CAST(o.id AS TEXT) LIKE ? OR pd_fold(o.origin) LIKE ? OR pd_fold(o.destination) LIKE ? OR pd_fold(u.name) LIKE ? OR pd_fold(u.phone) LIKE ? OR pd_fold(p.name) LIKE ? OR pd_fold(p.plate) LIKE ?)")
            params.extend(['%'+q.casefold()+'%']*7)
        day=args.get('date','')
        if day:
            try:day=datetime.strptime(day,'%Y-%m-%d').strftime('%d.%m.%Y')
            except ValueError:raise ValueError('Некорректная дата фильтра') from None
            where.append('o.trip_date=?');params.append(day)
        with core.db(core.ORDERS_DB) as c:
            c.create_function('pd_fold',1,lambda value:str(value or '').casefold(),deterministic=True)
            c.execute('ATTACH DATABASE ? AS console_users',(str(core.USERS_DB),))
            sql='''SELECT o.id,o.telegram_id,o.origin,o.destination,o.stop_address,o.trip_date,o.trip_time,
             o.status,o.price,o.payment_status,o.payment_method,o.passengers,o.luggage,o.details,
             a.pilot_id,u.name AS customer_name,u.phone AS customer_phone,p.name AS pilot_name,p.plate,
             t.arrived_at,t.started_at,t.ended_at,t.final_cents,t.wait_cents
             FROM orders o LEFT JOIN pd_pilot_assignments a ON a.order_id=o.id
             LEFT JOIN console_users.users u ON u.telegram_id=o.telegram_id
             LEFT JOIN console_users.pd_driver_applications p ON p.telegram_id=a.pilot_id
             LEFT JOIN pd_trip_runtime_v4 t ON t.order_id=o.id'''
            rows=[dict(r) for r in c.execute(sql+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY o.id DESC LIMIT ?',(*params,limit+1))]
            counts={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM orders GROUP BY status')}
            unpaid=c.execute("SELECT COUNT(*) FROM orders WHERE payment_status!='Оплачено' AND status NOT IN ('Отменена','Выполнена')").fetchone()[0]
        now=int(core.now().timestamp())
        for r in rows:r['drive_seconds']=max(0,(r['ended_at'] or now)-r['started_at']) if r['started_at'] else None
        return jsonify(orders=rows[:limit],next_before=rows[limit-1]['id'] if len(rows)>limit else None,counts=counts,unpaid=unpaid,server_now=now)

    @app.get('/api/admin/console/orders/<int:oid>')
    def pd_admin_console_order(oid):
        admin()
        response=app.view_functions['pd_v4_admin_trip'](oid)
        data=response.get_json() if hasattr(response,'get_json') else response
        with core.db(core.ORDERS_DB) as c:
            current=snapshot(c,oid)
            history=[dict(r) for r in c.execute('SELECT * FROM pd_admin_order_audit_v4 WHERE order_id=? ORDER BY id DESC LIMIT 100',(oid,))]
            reason=locks(c,current)
            price_history=[dict(r) for r in c.execute('SELECT * FROM pd_price_changes WHERE order_id=? ORDER BY id DESC LIMIT 100',(oid,))] if table(c,'pd_price_changes') else []
            pilot_history=[dict(r) for r in c.execute('SELECT * FROM pd_pilot_assignment_log WHERE order_id=? ORDER BY id DESC LIMIT 100',(oid,))] if table(c,'pd_pilot_assignment_log') else []
        for event in history:
            event['before']=json.loads(event.pop('before_json'));event['after']=json.loads(event.pop('after_json'))
        data.update(revision=revision(current),admin_note=current['admin_note'],edit_locks=reason,audit=history,price_history=price_history,pilot_history=pilot_history)
        return jsonify(data)

    @app.post('/api/admin/console/orders/<int:oid>')
    def pd_admin_console_edit(oid):
        uid=admin();body=request.get_json(silent=True) or {};changes=body.get('changes')
        reason=str(body.get('reason','')).strip()
        if not 3<=len(reason)<=500 or not isinstance(changes,dict) or not changes or set(changes)-EDITABLE-{'admin_note'}:
            raise ValueError('Укажите допустимые поля и причину изменения')
        if not isinstance(body.get('revision'),str):raise ValueError('Обновите карточку заказа')
        with core.db(core.ORDERS_DB) as c:
            c.execute('BEGIN IMMEDIATE');old=snapshot(c,oid)
            if revision(old)!=body['revision']:return jsonify(error='Заказ изменился. Обновите карточку перед сохранением.'),409
            reasons=locks(c,old)
            if set(changes)-{'admin_note'} and reasons:raise ValueError('Прямое изменение параметров недоступно: '+'. '.join(reasons))
            updates={};prospective=dict(old)
            for key,value in changes.items():
                if key=='passengers':
                    if type(value) is not int or not 1<=value<=int(getattr(core,'MAX_PASSENGERS',4)):raise ValueError('Проверьте число пассажиров')
                else:
                    if not isinstance(value,str):raise ValueError('Некорректное значение поля')
                    value=value.strip()
                    maximum=2000 if key in ('details','admin_note') else 200
                    if len(value)>maximum:raise ValueError('Слишком длинное значение')
                    if key in ('origin','destination') and len(value)<2:raise ValueError('Укажите полный адрес')
                    if key=='trip_date':date(value)
                    if key=='trip_time' and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ValueError('Время должно быть в формате ЧЧ:ММ')
                prospective[key]=value
                if value!=old.get(key):updates[key]=value
            if not updates:return jsonify(ok=True,replayed=True,revision=revision(old))
            if set(updates)-{'admin_note'}:
                if prospective['origin'].casefold()==prospective['destination'].casefold():raise ValueError('Адреса подачи и назначения совпадают')
                depart=datetime.strptime(prospective['trip_date']+' '+prospective['trip_time'],'%d.%m.%Y %H:%M').replace(tzinfo=core.now().tzinfo)
                if depart<=core.now():raise ValueError('Укажите будущую дату и время подачи')
                # A changed trip must be priced/reconfirmed; never reuse the old quote.
                updates.update(price='',status='Новая',quote_status='Требуется пересчёт',distance_km=None,duration_min=None,route_source=None)
                for name in ('pd_order_points','pd_order_map_points'):
                    if table(c,name):c.execute('DELETE FROM '+name+' WHERE order_id=?',(oid,))
            note=updates.pop('admin_note',None)
            if note is not None:
                c.execute('INSERT INTO pd_admin_order_notes_v4 VALUES(?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET note=excluded.note,updated_at=excluded.updated_at,admin_id=excluded.admin_id',(oid,note,core.now().isoformat(),uid))
            if updates:
                updates['updated_at']=core.now().isoformat()
                c.execute('UPDATE orders SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),oid))
            new=snapshot(c,oid);audit(c,oid,uid,'edit_order',reason,old,new)
        # No provider requests or passenger messages are generated by an editor save.
        return jsonify(ok=True,revision=revision(new),needs_reprice=bool(set(changes)-{'admin_note'}))

    @app.post('/api/admin/console/orders/<int:oid>/action')
    def pd_admin_console_action(oid):
        uid=admin();body=request.get_json(silent=True) or {};reason=str(body.get('reason','')).strip()
        if body.get('action') not in ('arrive','start','finish') or not 3<=len(reason)<=500:
            raise ValueError('Укажите действие и причину')
        transition=app.config.get('PD_TRIP_TRANSITION_V4')
        if not transition:raise ValueError('Сценарий поездки ещё не подключён')
        # Transition itself locks the row and checks payment/state; all changes share its transaction.
        return jsonify(transition(oid,body['action'],uid,admin_reason=reason))

    @app.before_request
    def pd_admin_console_assignment_guard():
        if request.method!='POST' or not request.path.startswith('/api/admin/pilot-assignments/'):
            return
        admin()
        oid=(request.view_args or {}).get('oid')
        with core.db(core.ORDERS_DB) as c:
            trip=c.execute('SELECT arrived_at,started_at FROM pd_trip_runtime_v4 WHERE order_id=?',(oid,)).fetchone()
        if trip and (trip['arrived_at'] or trip['started_at']):
            raise ValueError('Нельзя менять назначенного пилота после прибытия. Сначала завершите или отмените текущую поездку.')
