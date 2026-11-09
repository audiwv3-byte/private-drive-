"""Run on the application host. Atomic test-data reset; no bot imports or messages."""
import argparse,hashlib,json,os,re,sqlite3,time
from pathlib import Path
from reset_logic import USER_TABLES,ORDER_TABLES,USER_SETTINGS,ORDER_SETTINGS

def run(root,backup):
 root=root.resolve();backup=backup.resolve()
 assert root not in backup.parents and backup!=root
 backup.mkdir(parents=True,exist_ok=True);backup.chmod(0o700)
 env={}
 for line in (root/'.env').read_text().splitlines():
  m=re.match(r'\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)',line)
  if m:env[m[1]]=m[2].strip().strip('\"\'')
 admins={int(x.strip()) for x in env.get('ADMIN_IDS','').split(',') if x.strip().isdigit()};assert len(admins)==1
 admin=next(iter(admins));cutoff=int(time.time())
 c=sqlite3.connect(root/'orders.db',timeout=25);c.execute('PRAGMA busy_timeout=25000')
 c.execute('ATTACH DATABASE ? AS profiles',(str(root/'users.db'),))
 def tables(schema):return {r[0] for r in c.execute("SELECT name FROM "+schema+".sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
 def columns(schema,table):return {r[1] for r in c.execute('PRAGMA '+schema+'.table_info('+table+')')}
 def count(schema):return {t:c.execute('SELECT COUNT(*) FROM '+schema+'.'+t).fetchone()[0] for t in sorted(tables(schema))}
 def rows(schema,table):return c.execute('SELECT * FROM '+schema+'.'+table).fetchall()
 try:
  c.execute('BEGIN IMMEDIATE')
  assert tables('profiles')<=USER_TABLES and tables('main')<=ORDER_TABLES,'Unknown table requires review'
  for schema in ('main','profiles'):
   assert c.execute('PRAGMA '+schema+'.quick_check').fetchone()[0]=='ok'
   for table in tables(schema):
    cols=columns(schema,table)
    if 'mode' in cols:assert c.execute('SELECT COUNT(*) FROM '+schema+'.'+table+" WHERE mode='live'").fetchone()[0]==0,'Live payment record conflicts with test reset'
    for col in ('stripe_session_id','session_id','stripe_checkout_session_id'):
     if col in cols:assert c.execute('SELECT COUNT(*) FROM '+schema+'.'+table+' WHERE '+col+" LIKE 'cs_live_%'").fetchone()[0]==0,'Live checkout conflicts with test reset'
  preserved=c.execute('SELECT * FROM profiles.users WHERE telegram_id=?',(admin,)).fetchall();assert len(preserved)==1
  before=dict(users=count('profiles'),orders=count('main'))
  settings={(schema,t):rows(schema,t) for schema,settings in [('main',ORDER_SETTINGS),('profiles',USER_SETTINGS)] for t in tables(schema)&settings}
  ids=set()
  for schema in ('main','profiles'):
   for table in tables(schema):
    for col in columns(schema,table)&{'telegram_id','uid','owner_id','pilot_id','invitee','inviter'}:
     ids.update(r[0] for r in c.execute('SELECT DISTINCT '+col+' FROM '+schema+'.'+table) if type(r[0])is int and 0<r[0]<2**52 and r[0]not in admins)
  # BEGIN IMMEDIATE holds both databases against writers. Separate read connections
  # take SQLite backups while those locks remain held, producing a coherent pair.
  for name in ('orders.db','users.db'):
   destination=backup/name;assert not destination.exists(),'Backup already exists'
   source=sqlite3.connect((root/name).as_uri()+'?mode=ro',uri=True);target=sqlite3.connect(destination)
   try:source.backup(target);assert target.execute('PRAGMA quick_check').fetchone()[0]=='ok'
   finally:source.close();target.close()
   destination.chmod(0o600)
  manifest={'at':cutoff,'files':{name:hashlib.sha256((backup/name).read_bytes()).hexdigest() for name in ('orders.db','users.db')}}
  (backup/'DATABASE_MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True));(backup/'DATABASE_MANIFEST.json').chmod(0o600)
  for schema in ('main','profiles'):c.execute('PRAGMA '+schema+'.secure_delete=ON')
  for table in sorted(tables('profiles')-USER_SETTINGS-{'pd_revoked_sessions'}):
   if table in ('users','pd_passenger_profile','pd_customer_notes'):c.execute('DELETE FROM profiles.'+table+' WHERE telegram_id!=?',(admin,))
   elif table=='pd_profile_avatars_v6':c.execute('DELETE FROM profiles.'+table+' WHERE uid!=?',(admin,))
   else:c.execute('DELETE FROM profiles.'+table)
  c.execute('CREATE TABLE IF NOT EXISTS profiles.pd_revoked_sessions(telegram_id INTEGER PRIMARY KEY,not_before INTEGER NOT NULL)')
  c.executemany('INSERT INTO profiles.pd_revoked_sessions VALUES(?,?) ON CONFLICT(telegram_id) DO UPDATE SET not_before=MAX(not_before,excluded.not_before)',[(uid,cutoff) for uid in sorted(ids)])
  for table in sorted(tables('main')-ORDER_SETTINGS):c.execute('DELETE FROM main.'+table)
  assert c.execute('SELECT * FROM profiles.users WHERE telegram_id=?',(admin,)).fetchall()==preserved
  assert c.execute('SELECT COUNT(*) FROM profiles.users').fetchone()[0]==1
  assert all(rows(schema,table)==value for (schema,table),value in settings.items())
  for schema in ('main','profiles'):
   assert c.execute('PRAGMA '+schema+'.quick_check').fetchone()[0]=='ok'
   assert not c.execute('PRAGMA '+schema+'.foreign_key_check').fetchall()
  after=dict(users=count('profiles'),orders=count('main'))
  c.commit()
  result=dict(before=before,after=after,revoked_ids=sorted(ids),dispatcher_ids=sorted(admins),cutoff=cutoff,backup=str(backup),database_backup_manifest=manifest)
  (backup/'RESULT.json').write_text(json.dumps(result));(backup/'RESULT.json').chmod(0o600)
  return result
 except BaseException:c.rollback();raise
 finally:c.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--backup',type=Path,required=True);p.add_argument('--status',type=Path,required=True);a=p.parse_args()
 try:run(a.root,a.backup);a.status.write_text('OK');a.status.chmod(0o600)
 except BaseException:a.status.write_text('FAILED');a.status.chmod(0o600);raise
