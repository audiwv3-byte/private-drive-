"""Inspect reset scope privately; no hosting mutation."""
import ast,base64,hashlib,json,os,re,sqlite3,tempfile
from pathlib import Path
import requests
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
HOST='https://www.pythonanywhere.com/api/v0/user/wilsonpark'
PROJECT='/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/'
token=''.join(re.sub(r'^Token\s+','',os.environ.get('PA_API_TOKEN','').strip(),flags=re.I).split());assert token
session=requests.Session();session.headers['Authorization']='Token '+token
def api(method,path,**kwargs):
 r=session.request(method,HOST+path,timeout=40,**kwargs)
 assert r.status_code in (200,201,202,204),'Hosting request failed '+str(r.status_code)
 return r
def get(name):return api('GET','/files/path'+PROJECT+name).content
def encrypt(result):
 key=os.urandom(32);nonce=os.urandom(12);public=load_pem_public_key(Path(__file__).with_name('public-key.pem').read_bytes())
 wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
 data=AESGCM(key).encrypt(nonce,json.dumps(result,ensure_ascii=False).encode(),b'PRIVATE_DRIVE_AUDIT_20261109')
 enc=lambda x:base64.b64encode(x).decode()
 print('ENCRYPTED_AUDIT_RESULT',json.dumps(dict(key=enc(wrapped),nonce=enc(nonce),ciphertext=enc(data))))
def env_values():
 values={}
 for line in get('.env').decode('utf-8-sig').splitlines():
  m=re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)',line)
  if m:values[m[1]]=m[2].strip().strip('\"\'')
 return values
if __name__=='__main__':
 result={};env=env_values();admins={int(x.strip()) for x in env.get('ADMIN_IDS','').split(',') if x.strip().isdigit()}
 result['admin_config_count']=len(admins)
 meta=api('GET','/webapps/wilsonpark.pythonanywhere.com/').json()
 result['webapp']={k:v for k,v in meta.items() if k in ('enabled','is_enabled','state','status','source_directory','python_version','virtualenv_path','wsgi_configuration_file')}
 tasks=api('GET','/always_on/').json()
 result['tasks']=[dict(keys=sorted(t.keys()),id=t.get('id'),project_match=PROJECT.rstrip('/') in str(t.get('command','')),bot_match='Euro_Baltic_Transfer.py' in str(t.get('command','')),enabled=t.get('enabled'),state=t.get('state'),status=t.get('status')) for t in tasks]
 with tempfile.TemporaryDirectory() as directory:
  for name in ('users.db','orders.db'):
   p=Path(directory)/name;p.write_bytes(get(name));c=sqlite3.connect(p);c.row_factory=sqlite3.Row
   result[name]={}
   for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
    table=r[0];assert re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',table)
    columns=[r[1] for r in c.execute('PRAGMA table_info('+table+')')]
    detail=dict(count=c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],columns=columns)
    if 'mode' in columns:detail['live_mode_rows']=c.execute('SELECT COUNT(*) FROM '+table+" WHERE mode='live'").fetchone()[0]
    if 'livemode' in columns:detail['live_flag_rows']=c.execute('SELECT COUNT(*) FROM '+table+' WHERE livemode=1').fetchone()[0]
    result[name][table]=detail
   if name=='users.db':result['registered_admins']=sum(c.execute('SELECT COUNT(*) FROM users WHERE telegram_id=?',(uid,)).fetchone()[0] for uid in admins)
   c.close()
 core=get('Euro_Baltic_Transfer.py').decode('utf-8-sig');tree=ast.parse(core)
 result['core_admin_assignment']=[ast.get_source_segment(core,n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ADMIN_IDS' for t in n.targets)]
 result['client_button_markers']={text:core.count(text) for text in ('Как клиент','как клиент','Клиент','admin:client','role:client')}
 encrypt(result)
 print('INSPECT_RESET_DONE hosting_writes=0')
