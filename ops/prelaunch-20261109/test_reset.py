import sqlite3,tempfile,unittest,urllib.parse
from pathlib import Path
from types import SimpleNamespace
from reset_logic import clean_databases,patch_sources,GUARD
from reset_remote import run as attached_reset
from contextlib import contextmanager
@contextmanager
def db(path):
 c=sqlite3.connect(path)
 try:
  with c:yield c
 finally:c.close()

class ResetTests(unittest.TestCase):
 def test_remote_transaction_and_consistent_backup(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   root=Path(folder)/'app';root.mkdir();backup=Path(folder)/'private-backup';(root/'.env').write_text('ADMIN_IDS=999\n')
   with db(root/'users.db') as c:c.executescript("CREATE TABLE users(telegram_id INTEGER PRIMARY KEY,name TEXT);INSERT INTO users VALUES(999,'ADMIN'),(101,'TEST');CREATE TABLE pd_driver_applications(telegram_id INTEGER,status TEXT);INSERT INTO pd_driver_applications VALUES(101,'approved')")
   with db(root/'orders.db') as c:c.executescript('CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER);INSERT INTO orders(telegram_id) VALUES(101)')
   result=attached_reset(root,backup);self.assertEqual(result['after']['users']['users'],1);self.assertEqual(result['after']['orders']['orders'],0)
   with db(backup/'orders.db') as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
   with db(backup/'users.db') as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],2)
 def test_dispatcher_settings_and_revocation(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   users=Path(folder)/'users.db';orders=Path(folder)/'orders.db'
   with db(users) as c:
    c.executescript("CREATE TABLE users(telegram_id INTEGER PRIMARY KEY,name TEXT); INSERT INTO users VALUES(999,'ADMIN'),(101,'TEST'),(202,'TEST PILOT'); CREATE TABLE pd_driver_applications(telegram_id INTEGER,status TEXT);INSERT INTO pd_driver_applications VALUES(202,'approved');CREATE TABLE dialogue_states(telegram_id INTEGER,payload TEXT);INSERT INTO dialogue_states VALUES(101,'test');CREATE TABLE ref_promos(code TEXT,points INTEGER);INSERT INTO ref_promos VALUES('SAVE',10);CREATE TABLE pd_passenger_profile(telegram_id INTEGER,name TEXT);INSERT INTO pd_passenger_profile VALUES(999,'ADMIN'),(101,'TEST')")
   with db(orders) as c:
    c.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER,stripe_session_id TEXT);INSERT INTO orders(telegram_id) VALUES(101),(202);CREATE TABLE pd_invoice_settings(singleton INTEGER,data TEXT);INSERT INTO pd_invoice_settings VALUES(1,'KEEP SETTINGS');CREATE TABLE pd_cancellations(mode TEXT);INSERT INTO pd_cancellations VALUES('test')")
   result=clean_databases(users,orders,{999},1000)
   self.assertEqual(result['after']['users']['users'],1);self.assertEqual(result['after']['orders']['orders'],0);self.assertEqual(result['revoked_ids'],[101,202])
   with db(orders) as c:
    self.assertEqual(c.execute('SELECT seq FROM sqlite_sequence WHERE name=\'orders\'').fetchone()[0],2)
    self.assertEqual(c.execute('SELECT data FROM pd_invoice_settings').fetchone()[0],'KEEP SETTINGS')
   scope={'urllib':__import__('urllib')};exec(GUARD,scope)
   core=SimpleNamespace(db=lambda p:sqlite3.connect(p),USERS_DB=users)
   with self.assertRaises(PermissionError):scope['enforce_session_revocation'](core,101,'auth_date=1000')
   scope['enforce_session_revocation'](core,101,'auth_date=1001');scope['enforce_session_revocation'](core,999,'auth_date=500')
 def test_live_rows_block_before_delete(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   users=Path(folder)/'u.db';orders=Path(folder)/'o.db'
   with db(users) as c:c.execute('CREATE TABLE users(telegram_id INTEGER)');c.execute('INSERT INTO users VALUES(999)')
   with db(orders) as c:c.execute('CREATE TABLE pd_prepayments(mode TEXT)');c.execute("INSERT INTO pd_prepayments VALUES('live')")
   with self.assertRaisesRegex(AssertionError,'Live financial'):clean_databases(users,orders,{999},1000)
   with db(orders) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM pd_prepayments').fetchone()[0],1)
 def test_exact_source_patch_and_dispatcher_button(self):
  page=(Path(__file__).parent/'live-index.html').read_text(encoding='utf-8')
  server,security,page=patch_sources("def auth():\n    return telegram_user(request.headers.get('X-Telegram-Init-Data', ''))\n",'import urllib.parse\n',page)
  self.assertTrue('uid, user = telegram_user(init_data)' in server);self.assertTrue('enforce_session_revocation' in security);self.assertTrue('Как клиент</button>' not in page);self.assertTrue('<button type="button" data-mode="client"' not in page)

if __name__=='__main__':unittest.main()
