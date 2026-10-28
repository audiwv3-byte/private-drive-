"""Private change history; snapshots stay in USERS_DB and are readable only by admins."""
import json
from flask import request,jsonify

def ensure_tables(core):
    with core.db(core.USERS_DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS pd_profile_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,
          occurred_at TEXT NOT NULL,source TEXT NOT NULL,action TEXT NOT NULL,
          before_data TEXT NOT NULL,after_data TEXT NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS pd_profile_history_user ON pd_profile_history(telegram_id,id)')
        for table,fields in [('users',['name','phone']),('pd_passenger_profile',['first_name','last_name','username','language_code','email','home_city','preferences'])]:
            columns={r['name'] for r in c.execute('PRAGMA table_info('+table+')')}
            if not columns:continue
            key='telegram_id' if 'telegram_id' in columns else 'id'
            fields=[f for f in fields if f in columns]
            assert fields and key in columns
            def obj(prefix):return 'json_object('+','.join("'"+f+"',"+prefix+'."'+f+'"' for f in fields)+')'
            old,new=obj('OLD'),obj('NEW')
            current=obj('u')
            c.execute(f'''INSERT INTO pd_profile_history(telegram_id,occurred_at,source,action,before_data,after_data)
              SELECT u."{key}",strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,'baseline','{{}}',{current}
              FROM {table} u WHERE NOT EXISTS(SELECT 1 FROM pd_profile_history h WHERE h.telegram_id=u."{key}" AND h.source=?)''',(table,table))
            changed=' OR '.join(f'OLD."{f}" IS NOT NEW."{f}"' for f in fields)
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS pd_history_{table}_update AFTER UPDATE ON {table}
              WHEN {changed} BEGIN
              INSERT INTO pd_profile_history(telegram_id,occurred_at,source,action,before_data,after_data)
              VALUES(NEW."{key}",strftime('%Y-%m-%dT%H:%M:%fZ','now'),'{table}','updated',{old},{new}); END''')
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS pd_history_{table}_insert AFTER INSERT ON {table}
              WHEN {new} IS NOT (SELECT after_data FROM pd_profile_history WHERE telegram_id=NEW."{key}" AND source='{table}' ORDER BY id DESC LIMIT 1)
              BEGIN INSERT INTO pd_profile_history(telegram_id,occurred_at,source,action,before_data,after_data)
              VALUES(NEW."{key}",strftime('%Y-%m-%dT%H:%M:%fZ','now'),'{table}',
                CASE WHEN EXISTS(SELECT 1 FROM pd_profile_history WHERE telegram_id=NEW."{key}" AND source='{table}') THEN 'updated' ELSE 'created' END,
                COALESCE((SELECT after_data FROM pd_profile_history WHERE telegram_id=NEW."{key}" AND source='{table}' ORDER BY id DESC LIMIT 1),'{{}}'),{new}); END''')

def register(app,core,auth):
    ensure_tables(core)
    @app.get('/api/admin/customers/<int:customer>/profile-history')
    def pd_profile_history_list(customer):
        uid,_=auth()
        if not core.is_admin(uid):raise PermissionError('Нет доступа')
        before=request.args.get('before',type=int)
        where='telegram_id=?'+(' AND id<?' if before else '')
        args=(customer,before) if before else (customer,)
        with core.db(core.USERS_DB) as c:
            rows=c.execute('SELECT * FROM pd_profile_history WHERE '+where+' ORDER BY id DESC LIMIT 101',args).fetchall()
        events=[]
        for row in rows[:100]:
            item=dict(row);item['before']=json.loads(item.pop('before_data'));item['after']=json.loads(item.pop('after_data'));events.append(item)
        return jsonify(events=events,next_before=rows[99]['id'] if len(rows)>100 else None)
