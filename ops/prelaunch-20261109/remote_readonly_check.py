"""Ephemeral read-only production check. Never publishes sources or databases."""
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import requests
from test_runtime_contracts import run
import base64
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HOST='https://www.pythonanywhere.com/api/v0/user/wilsonpark'
PROJECT='/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/'
token=''.join(re.sub(r'^Token\s+','',os.environ.get('PA_API_TOKEN','').strip(),flags=re.I).split())
assert token,'BLOCKED missing existing hosting credential'
session=requests.Session();session.headers['Authorization']='Token '+token
findings={}
def fetch(name,optional=False):
    response=session.get(HOST+'/files/path'+PROJECT+name,timeout=35)
    if optional and response.status_code==404:return None
    if response.status_code!=200:raise RuntimeError('Read failed '+name+' HTTP '+str(response.status_code))
    return response.content

with tempfile.TemporaryDirectory(prefix='pd-private-audit-') as directory:
    root=Path(directory)
    runtime=fetch('pd_trip_runtime_v4.py')
    tree=ast.parse(runtime.decode('utf-8-sig'))
    allowed_imports={'json','math','time','decimal','flask'}
    for node in tree.body:
        if isinstance(node,ast.Import):assert all(x.name in allowed_imports for x in node.names)
        elif isinstance(node,ast.ImportFrom):assert node.module in allowed_imports
        else:assert isinstance(node,(ast.FunctionDef,ast.Assign)) or isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)
    path=root/'runtime.py';path.write_bytes(runtime)
    print('LIVE_RUNTIME_SHA256',hashlib.sha256(runtime).hexdigest())
    run(path)
    for name in ('orders.db','users.db'):
        wal=fetch(name+'-wal',optional=True)
        assert not wal,'BLOCKED database uses WAL; requires consistent hosting snapshot'
        content=fetch(name)
        assert content.startswith(b'SQLite format 3\x00')
        (root/name).write_bytes(content)
    # Require the source bytes to remain stable over the complete pair download.
    for name in ('orders.db','users.db'):
        assert hashlib.sha256(fetch(name)).digest()==hashlib.sha256((root/name).read_bytes()).digest(),'BLOCKED database changed during read; retry from consistent snapshot'
    orders=sqlite3.connect((root/'orders.db').as_uri()+'?mode=ro',uri=True);orders.row_factory=sqlite3.Row
    users=sqlite3.connect((root/'users.db').as_uri()+'?mode=ro',uri=True);users.row_factory=sqlite3.Row
    for c in (orders,users):
        assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert c.execute('PRAGMA journal_mode').fetchone()[0]!='wal'
        c.execute('PRAGMA query_only=ON')
    tables=lambda c:{r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def enum(value,allowed):return value if value in allowed else 'UNRECOGNIZED'
    payment_states={'Оплачено','Не оплачено','Перевод на проверке','Криптоперевод на проверке','Ожидается оплата наличными',''}
    trip_states={'Новая','Подтверждена','В пути','Выполнена','Отменена'}
    pilot_states={'approved','pending','rejected','stage2'}
    order=orders.execute('SELECT status,payment_status,payment_method FROM orders WHERE id=24').fetchone()
    if order:
        findings['order24']=dict(status=enum(order['status'],trip_states),payment_status=enum(order['payment_status'],payment_states),payment_status_has_whitespace=order['payment_status']!=str(order['payment_status']).strip(),payment_method=enum(order['payment_method'],{'Наличные','Наличными','Банковский перевод','Криптовалюта','Онлайн (Stripe)','Банковская карта'}))
    else:findings['order24']={'exists':False}
    if 'pd_pilot_assignments' in tables(orders):
        assignment=orders.execute('SELECT pilot_id FROM pd_pilot_assignments WHERE order_id=24').fetchone()
        driver=users.execute('SELECT status,stage FROM pd_driver_applications WHERE telegram_id=?',(assignment['pilot_id'],)).fetchone() if assignment else None
        findings['order24_pilot']=dict(assigned=bool(assignment),application_exists=bool(driver),approval=enum(driver['status'],pilot_states) if driver else None,stage=driver['stage'] if driver else None)
    findings['pilot_counts']={enum(r['status'],pilot_states):r['n'] for r in users.execute('SELECT status,COUNT(*) AS n FROM pd_driver_applications GROUP BY status')}
    def pseudonym(value):return hashlib.sha256(('pd-audit:'+str(value)).encode()).hexdigest()[:12]
    required1={'license_front','license_back','car_front','car_rear','car_interior'}
    required2={'registration_front','ltsa','activity','insurance','portrait'}
    findings['pilot_history']=[]
    for row in users.execute('SELECT telegram_id,status,stage,created_at,updated_at FROM pd_driver_applications ORDER BY updated_at DESC LIMIT 20'):
        sides={r[0] for r in users.execute('SELECT side FROM pd_driver_documents WHERE telegram_id=?',(row['telegram_id'],))} if 'pd_driver_documents' in tables(users) else set()
        findings['pilot_history'].append(dict(identity=pseudonym(row['telegram_id']),status=enum(row['status'],pilot_states),stage=row['stage'],created_at=row['created_at'],updated_at=row['updated_at'],document_sides=sorted(sides),missing_stage1=sorted(required1-sides),missing_stage2=sorted((required1|required2)-sides)))
    if 'pd_driver_application_decisions' in tables(users):
        findings['pilot_decisions']=[dict(identity=pseudonym(r['telegram_id']),old=enum(r['old_status'],pilot_states),new=enum(r['new_status'],pilot_states),at=r['decided_at']) for r in users.execute('SELECT telegram_id,old_status,new_status,decided_at FROM pd_driver_application_decisions ORDER BY id DESC LIMIT 30')]
    if 'pd_pilot_assignment_log' in tables(orders):
        findings['assignment_history']=[dict(order_id=r['order_id'],pilot=pseudonym(r['pilot_id']) if r['pilot_id'] else None,at=r['changed_at']) for r in orders.execute('SELECT order_id,pilot_id,changed_at FROM pd_pilot_assignment_log ORDER BY id DESC LIMIT 30')]
    for table in ('pd_cash_receipts','pd_bank_transfers','pd_prepayments','pd_booking_capture_v4'):
        if table not in tables(orders):continue
        columns={r[1] for r in orders.execute('PRAGMA table_info('+table+')')}
        if 'order_id' in columns:
            row=orders.execute('SELECT * FROM '+table+' WHERE order_id=24').fetchone()
            safe={'exists':bool(row)}
            for key in ('state','status'):
                if row and key in columns:safe[key]=enum(row[key],{'pending','paid','received','claimed','succeeded','authorized','checkout','creating','capturing','failed','canceled','Оплачено','На проверке'})
            findings.setdefault('order24_ledgers',{})[table]=safe
    orders.close();users.close()
    # Only configuration presence is returned; never return a credential or account.
    env=fetch('.env',optional=True)
    findings['saved_payment_config']={}
    if env:
        for line in env.decode('utf-8-sig').splitlines():
            match=re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)',line)
            if match and re.search('PAYPAL|PAYSEND|STRIPE|PD_PAYMENT_MODE',match[1],re.I):
                key,value=match.groups();value=value.strip().strip('\"\'')
                findings['saved_payment_config'][key]=value if key=='PD_PAYMENT_MODE' and value in ('disabled','test','live') else bool(value)
    core_source=fetch('Euro_Baltic_Transfer.py').decode('utf-8-sig')
    core_tree=ast.parse(core_source)
    definitions={target.id:ast.get_source_segment(core_source,node.value) for node in core_tree.body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name) and target.id in ('ROOT','ORDERS_DB','USERS_DB')}
    findings['database_path_definitions']=definitions
    meta=session.get(HOST+'/webapps/wilsonpark.pythonanywhere.com/',timeout=35)
    if meta.status_code==200:
        data=meta.json();findings['hosting_source_directory_matches']=str(data.get('source_directory','')).rstrip('/')==PROJECT.rstrip('/')
    # Compare prior verified backups without modifying or restoring them.
    backup_root='/home/wilsonpark/private_drive_backups/'
    listing=session.get(HOST+'/files/tree/',params={'path':backup_root},timeout=35)
    if listing.status_code==200:
        entries=listing.json()
        if isinstance(entries,list):
            candidates=sorted({str(item) for item in entries if str(item).startswith(backup_root) and str(item).endswith('/users.db')})[-4:]
            findings['backup_pilot_counts']=[]
            for index,remote in enumerate(candidates):
                result=session.get(HOST+'/files/path'+remote,timeout=35)
                if result.status_code!=200:continue
                backup=root/('backup-users-'+str(index)+'.db');backup.write_bytes(result.content)
                c=sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
                if 'pd_driver_applications' in tables(c):
                    counts={enum(r['status'],pilot_states):r['n'] for r in c.execute('SELECT status,COUNT(*) AS n FROM pd_driver_applications GROUP BY status')}
                    backup_columns={r[1] for r in c.execute('PRAGMA table_info(pd_driver_applications)')}
                    stage='stage' if 'stage' in backup_columns else 'NULL AS stage'
                    people=[dict(identity=pseudonym(r['telegram_id']),status=enum(r['status'],pilot_states),stage=r['stage']) for r in c.execute('SELECT telegram_id,status,'+stage+' FROM pd_driver_applications')]
                    findings['backup_pilot_counts'].append(dict(snapshot=remote.split('/')[-2],counts=counts,pilots=people))
                c.close()
key=os.urandom(32);nonce=os.urandom(12)
public_key=load_pem_public_key(Path(__file__).with_name('public-key.pem').read_bytes())
wrapped=public_key.encrypt(key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
ciphertext=AESGCM(key).encrypt(nonce,json.dumps(findings,ensure_ascii=False).encode(),b'PRIVATE_DRIVE_AUDIT_20261109')
encode=lambda b:base64.b64encode(b).decode('ascii')
print('ENCRYPTED_AUDIT_RESULT',json.dumps(dict(key=encode(wrapped),nonce=encode(nonce),ciphertext=encode(ciphertext))))
print('READONLY_DONE hosting_writes=0 real_messages=0 real_payments=0 sources_and_databases_not_uploaded=true')
# Public-only fixtures for the isolated DOM checks in the next job step.
fixture_root=Path(__file__).parent
public=requests.Session()
page=public.get('https://wilsonpark.pythonanywhere.com/',timeout=30);assert page.status_code==200
(fixture_root/'live-index.html').write_bytes(page.content)
(fixture_root/'public').mkdir(exist_ok=True)
for asset in sorted(set(re.findall(r'<script\b[^>]*src=[\"\'](/[^\"\']+)',page.text))):
    response=public.get('https://wilsonpark.pythonanywhere.com'+asset,timeout=30);assert response.status_code==200
    (fixture_root/'public'/Path(asset.split('?')[0]).name).write_bytes(response.content)
