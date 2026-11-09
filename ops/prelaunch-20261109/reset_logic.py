"""Pure reset transformations; production access belongs to a separate guarded runner."""
import ast
import hashlib
import sqlite3

USER_TABLES={'users','dialogue_states','ref_members','ref_rewards','ref_promos','ref_redemptions','pd_customer_notes','pd_passenger_profile','pd_driver_applications','pd_driver_application_decisions','pd_driver_documents','pd_profile_history','pd_profile_avatars_v6','ref_partner_rewards_v5','pd_revoked_sessions'}
ORDER_TABLES={'orders','pd_invoices','pd_cash_receipts','pd_price_changes','pd_adjustments','pd_service_reviews','pd_bank_transfers','pd_stripe_adjustments','pd_pilot_assignments','pd_pilot_assignment_log','pd_invoice_files','pd_invoice_settings','pd_invoice_settings_history','pd_prepayments','pd_cancellations','pd_payment_events','pd_extra_charges','pd_crypto_payments','pd_trip_runtime_v4','pd_trip_extras_v4','pd_trip_events_v4','pd_booking_capture_v4','pd_booking_cancel_v4','pd_trip_payment_events_v4','pd_admin_order_notes_v4','pd_admin_order_audit_v4','pd_pilot_assignment_notices','pd_crypto_quotes_v5','pd_crypto_quote_claims_v5','pd_passenger_location_v6','pd_pilot_payment_notices'}
ORDER_SETTINGS={'pd_invoice_settings','pd_invoice_settings_history'}
USER_SETTINGS={'ref_promos'}
GUARD='''

def enforce_session_revocation(core, uid, init_data):
    """A removed profile needs fresh Telegram initData before registering again."""
    connection = core.db(core.USERS_DB)
    try:
        present = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pd_revoked_sessions'").fetchone()
        record = connection.execute('SELECT not_before FROM pd_revoked_sessions WHERE telegram_id=?', (uid,)).fetchone() if present else None
    finally:
        connection.close()
    if record:
        auth_date = int(urllib.parse.parse_qs(init_data, strict_parsing=True)['auth_date'][0])
        if auth_date <= record[0]:
            raise PermissionError('Профиль удалён. Закройте приложение и откройте его заново через Telegram для новой регистрации.')
'''

def patch_sources(server,security,template):
    tree=ast.parse(server)
    auth=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='auth')
    assert not auth.args.args and len(auth.body)==1 and isinstance(auth.body[0],ast.Return),'Unexpected auth implementation'
    old=ast.get_source_segment(server,auth)
    replacement="""def auth():
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    uid, user = telegram_user(init_data)
    from pd_request_security import enforce_session_revocation
    enforce_session_revocation(core, uid, init_data)
    return uid, user"""
    assert server.count(old)==1 and 'def enforce_session_revocation(' not in security
    server=server.replace(old,replacement,1);security+=GUARD
    old_button=r'''<button class=\"secondary\" onclick=\"pdSetRole('client')\">Как клиент</button>'''
    assert template.count(old_button)==1,'Unexpected dispatcher client button'
    template=template.replace(old_button,'')
    role_button='''<button type="button" data-mode="client" onclick="pdSetRole('client')">Клиент</button>'''
    assert template.count(role_button)==1,'Unexpected dispatcher role bar'
    template=template.replace(role_button,'')
    driver_button=r'''<button class=\"secondary\" onclick=\"pdSetRole('driver')\">Водитель</button>'''
    assert template.count(driver_button)==1
    template=template.replace(driver_button,'')
    driver_role='''<button type="button" data-mode="driver" onclick="pdSetRole('driver')">Водитель</button>'''
    assert template.count(driver_role)==1
    template=template.replace(driver_role,'')
    assert template.count('function pdSetRole(mode){')==1
    template=template.replace('function pdSetRole(mode){',"function pdSetRole(mode){if(admin&&mode!=='admin')mode='admin';",1)
    assert 'Как клиент</button>' not in template
    ast.parse(server);ast.parse(security)
    return server,security,template

def tables(c):return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
def counts(c):return {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in sorted(tables(c))}
def clean_databases(user_path,order_path,admins,cutoff):
    assert len(admins)==1 and all(type(x)is int and 0<x<2**52 for x in admins),'Dispatcher identity is ambiguous'
    u=sqlite3.connect(user_path);o=sqlite3.connect(order_path)
    try:
        assert tables(u)<=USER_TABLES,'Unknown user table must be reviewed'
        assert tables(o)<=ORDER_TABLES,'Unknown order table must be reviewed'
        for c in (u,o):
            assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            for table in tables(c):
                columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
                if 'mode' in columns:assert c.execute('SELECT COUNT(*) FROM '+table+" WHERE mode='live'").fetchone()[0]==0,'Live financial record conflicts with test reset'
                if 'livemode' in columns:assert c.execute('SELECT COUNT(*) FROM '+table+' WHERE livemode=1').fetchone()[0]==0,'Live financial record conflicts with test reset'
                for column in ('stripe_session_id','session_id','stripe_checkout_session_id'):
                    if column in columns:assert c.execute('SELECT COUNT(*) FROM '+table+' WHERE '+column+" LIKE 'cs_live_%'").fetchone()[0]==0,'Live checkout conflicts with test reset'
        admin=next(iter(admins));preserved=u.execute('SELECT * FROM users WHERE telegram_id=?',(admin,)).fetchall();assert len(preserved)==1
        before={'users':counts(u),'orders':counts(o)}
        settings_before={}
        for label,c,settings in [('u',u,USER_SETTINGS),('o',o,ORDER_SETTINGS)]:
            for table in tables(c)&settings:settings_before[(label,table)]=c.execute('SELECT * FROM '+table).fetchall()
        removed=set()
        for c in (u,o):
            for table in tables(c):
                columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
                for column in ('telegram_id','uid','owner_id','pilot_id','invitee','inviter'):
                    if column in columns:
                        removed.update(r[0] for r in c.execute('SELECT DISTINCT '+column+' FROM '+table) if type(r[0])is int and 0<r[0]<2**52 and r[0]not in admins)
        for c in (u,o):c.execute('PRAGMA secure_delete=ON')
        with u:
            for table in sorted(tables(u)-USER_SETTINGS-{'pd_revoked_sessions'}):
                if table in ('users','pd_passenger_profile','pd_customer_notes'):
                    u.execute('DELETE FROM '+table+' WHERE telegram_id!=?',(admin,))
                elif table=='pd_profile_avatars_v6':u.execute('DELETE FROM '+table+' WHERE uid!=?',(admin,))
                else:u.execute('DELETE FROM '+table)
            u.execute('CREATE TABLE IF NOT EXISTS pd_revoked_sessions(telegram_id INTEGER PRIMARY KEY,not_before INTEGER NOT NULL)')
            u.executemany('INSERT INTO pd_revoked_sessions VALUES(?,?) ON CONFLICT(telegram_id) DO UPDATE SET not_before=MAX(not_before,excluded.not_before)',[(uid,cutoff) for uid in sorted(removed)])
        with o:
            for table in sorted(tables(o)-ORDER_SETTINGS):o.execute('DELETE FROM '+table)
        assert u.execute('SELECT * FROM users WHERE telegram_id=?',(admin,)).fetchall()==preserved
        assert u.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
        for label,c,settings in [('u',u,USER_SETTINGS),('o',o,ORDER_SETTINGS)]:
            for table in tables(c)&settings:assert c.execute('SELECT * FROM '+table).fetchall()==settings_before[(label,table)]
        for c in (u,o):
            assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
        after={'users':counts(u),'orders':counts(o)}
        return dict(before=before,after=after,revoked_ids=sorted(removed),dispatcher_ids=sorted(admins),cutoff=cutoff)
    finally:u.close();o.close()
