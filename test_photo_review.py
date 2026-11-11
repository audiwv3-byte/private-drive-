"""Isolated approval flow tests; no production identities or external calls."""
import io,sqlite3,tempfile,sys,types,importlib.util
from pathlib import Path
from datetime import datetime,timezone
from contextlib import contextmanager
from flask import Flask,request,jsonify
from PIL import Image
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
# HEIC decoding is provided on production; JPEG tests do not need that plugin.
sys.modules.setdefault('pillow_heif',types.SimpleNamespace(register_heif_opener=lambda:None))
spec=importlib.util.spec_from_file_location('pd_onboarding',HERE/'test_fixtures/pd_onboarding.py')
onboarding=importlib.util.module_from_spec(spec);sys.modules['pd_onboarding']=onboarding
sys.modules.setdefault('pd_languages',types.SimpleNamespace())
spec.loader.exec_module(onboarding)
import pd_live_home,pd_request_security
@contextmanager
def db(path):
 c=sqlite3.connect(path);c.row_factory=sqlite3.Row
 try:
  with c:yield c
 finally:c.close()
def jpeg(color):
 out=io.BytesIO();Image.new('RGB',(1200,800),color).save(out,'JPEG');return out.getvalue()
with tempfile.TemporaryDirectory() as tmp:
 core=types.SimpleNamespace(USERS_DB=tmp+'/users.db',ORDERS_DB=tmp+'/orders.db',db=db,is_admin=lambda uid:uid==999,now=lambda:datetime.now(timezone.utc))
 with db(core.USERS_DB) as c:
  c.execute('CREATE TABLE pd_driver_applications(telegram_id INTEGER PRIMARY KEY,name TEXT,status TEXT,stage INTEGER)')
  c.executemany('INSERT INTO pd_driver_applications VALUES(?,?,?,?)',[(101,'Pilot','approved',2),(102,'Other','approved',2),(103,'Stage one','pending',1)])
  c.execute('CREATE TABLE pd_driver_documents(telegram_id INTEGER,side TEXT,image BLOB,updated_at TEXT,PRIMARY KEY(telegram_id,side))')
  c.execute('INSERT INTO pd_driver_documents VALUES(?,?,?,?)',(101,'car_front',jpeg('blue'),'old'))
 app=Flask(__name__);app.testing=True
 @app.errorhandler(PermissionError)
 def permission(e):return jsonify(error=str(e)),401
 @app.errorhandler(ValueError)
 def invalid(e):return jsonify(error=str(e)),400
 def auth():return int(request.headers.get('Test-User',101)),{}
 pd_request_security.register_request_guard(app)
 pd_live_home.register(app,core,auth)
 @app.post('/api/driver/application')
 def application():return jsonify(ok=True)
 @app.get('/')
 def home():return '<html><body>Test</body></html>'
 client=app.test_client()
 def upload(kind='profile',uid=101,color='red',raw=None,path=None):
  return client.post(path or '/api/photo-review/upload/'+kind,headers={'Test-User':str(uid)},data={('photo' if kind=='profile' else kind):(io.BytesIO(raw or jpeg(color)),'photo.jpg')})
 def decide(rid,status='approved',uid=999,checked=True,reason=''):
  return client.post(f'/api/photo-review/{rid}/decision',headers={'Test-User':str(uid)},json={'status':status,'rules_checked':checked,'reason':reason})
 def active(uid=101):return client.get('/api/profile/avatar-v6?uid='+str(uid),headers={'Test-User':str(uid)})
 with db(core.USERS_DB) as c:c.execute('INSERT INTO pd_profile_avatars_v6 VALUES(?,?,?)',(101,jpeg('blue'),1))
 old=active().data
 r=upload(path='/api/profile/avatar-v6');assert r.status_code==200,r.data;rid=r.json['review_id']
 assert active().data==old
 assert client.get(f'/api/photo-review/{rid}/image',headers={'Test-User':'102'}).status_code==401
 assert 'no-store' in client.get(f'/api/photo-review/{rid}/image').headers['Cache-Control']
 assert decide(rid,uid=101).status_code==401
 assert decide(rid,checked=False).status_code==400
 assert decide(rid).status_code==200
 assert active().data!=old
 assert decide(rid).status_code==409
 approved=active().data
 rid=upload(color='green').json['review_id'];assert decide(rid,'rejected').status_code==400
 assert decide(rid,'rejected',reason='Лицо не видно').status_code==200
 assert active().data==approved
 assert client.get('/api/photo-review').json['photos'][0]['reason']=='Лицо не видно'
 stale=upload(color='red').json['review_id'];latest=upload(color='green').json['review_id']
 assert decide(stale).status_code==409
 assert active().data==approved
 assert decide(latest).status_code==200
 assert upload(uid=104).status_code==401
 assert upload(raw=b'not image').status_code==400
 assert upload('portrait',uid=103).status_code==400
 assert upload('unknown').status_code==400
 with db(core.USERS_DB) as c:old_doc=bytes(c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side='car_front'").fetchone()[0])
 rid=upload('car_front',color='red').json['review_id']
 with db(core.USERS_DB) as c:assert bytes(c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side='car_front'").fetchone()[0])==old_doc
 assert decide(rid).status_code==200
 with db(core.USERS_DB) as c:
  assert bytes(c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side='car_front'").fetchone()[0])!=old_doc
  assert c.execute('SELECT status FROM pd_driver_applications WHERE telegram_id=101').fetchone()[0]=='approved'
  assert c.execute('SELECT reviewer_id FROM pd_photo_reviews WHERE id=?',(rid,)).fetchone()[0]==999
 assert client.get('/api/photo-review?scope=pending',headers={'Test-User':'102'}).json['photos']==[]
 assert upload('car_front',path='/api/driver/application').status_code==400
 assert '/assets/pd-photo-review.js' in client.get('/').text
 assert client.get('/assets/pd-photo-review.js').status_code==200
 # Deletion is a withdrawal, so a dispatcher cannot approve a stale pending avatar.
 rid=upload(color='yellow').json['review_id'];assert client.delete('/api/profile/avatar-v6').status_code==200
 assert decide(rid).status_code==409
 print('PASS: private upload, unchanged approved photo, dispatcher-only approval, rule confirmation, rejection reason, superseded review, invalid files, staged document access, audit, no application bypass, withdrawal, UI script')
