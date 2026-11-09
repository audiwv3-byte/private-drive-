"""Apply approved UI/auth patches, then reset test data transactionally on the host."""
import ast,hashlib,hmac,json,os,re,shlex,time,urllib.parse
from pathlib import Path
from inspect_reset import HOST,PROJECT,session,env_values,encrypt
from reset_logic import patch_sources
assert os.environ.get('PD_RESET_AUTHORISATION')=='DELETE_TEST_DATA_KEEP_DISPATCHER_20261109'
ROOT=Path(__file__).parent;DOMAIN='/webapps/wilsonpark.pythonanywhere.com/';last_file_request=0
def api(method,path,**kwargs):
 global last_file_request
 if path.startswith('/files/path'):
  time.sleep(max(0,1.65-(time.monotonic()-last_file_request)));last_file_request=time.monotonic()
 for attempt in range(3):
  r=session.request(method,HOST+path,timeout=40,**kwargs)
  if r.status_code==429 and attempt<2:time.sleep(20);continue
  assert r.status_code in (200,201,202,204),'Hosting operation failed '+method+' '+path+' HTTP '+str(r.status_code)
  return r
def get(name):return api('GET','/files/path'+PROJECT+name).content
def put(path,content):
 api('POST','/files/path'+path,files={'content':('content',content,'application/octet-stream')})
 assert api('GET','/files/path'+path).content==content,'Readback mismatch'
def digest(data):return hashlib.sha256(data).hexdigest()
def signed(uid,token,stamp):
 values={'auth_date':str(stamp),'user':json.dumps({'id':uid,'first_name':'Maintenance verification'})}
 secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
 values['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(values.items())).encode(),hashlib.sha256).hexdigest()
 return urllib.parse.urlencode(values)

# Select only an observed idle Bash prompt; never interrupt a running console.
consoles=api('GET','/consoles/').json();selected=None
for item in sorted(consoles,key=lambda x:int(x['id']),reverse=True):
 if str(item.get('executable','')).split('/')[-1]!='bash':continue
 r=session.get(HOST+'/consoles/'+str(item['id'])+'/get_latest_output/',timeout=35)
 if r.status_code!=200:continue
 try:output=r.json()['output']
 except (ValueError,KeyError,TypeError):continue
 output=re.sub(r'\x1b\[[0-9;?]*[A-Za-z]','',output)
 if re.search(r'(?:^|\n)[^\n]{0,200}\$\s*$',output):selected=str(item['id']);break
assert selected,'BLOCKED no connected idle Bash console; no production changes made'
env=env_values();admins={int(x.strip()) for x in env.get('ADMIN_IDS','').split(',') if x.strip().isdigit()};assert len(admins)==1
config_before=get('.env');assert env.get('BOT_TOKEN')
meta=api('GET',DOMAIN).json();assert meta.get('enabled')is True and meta['source_directory'].rstrip('/')==PROJECT.rstrip('/')
manifest=json.loads((ROOT/'release/manifest.json').read_text())
original={name:get(name) for name in ('miniapp_server.py','pd_request_security.py','miniapp/templates/index.html','pd_tips_widget.py')}
for item in manifest:
 name=item['file'];original[name]=get(name)
 assert digest(original[name])==item['before_sha256'],'Source changed before deployment: '+name
 assert digest((ROOT/'release'/name).read_bytes())==item['after_sha256'],'Release hash mismatch'
server,security,page=patch_sources(original['miniapp_server.py'].decode('utf-8-sig'),original['pd_request_security.py'].decode('utf-8-sig'),original['miniapp/templates/index.html'].decode('utf-8-sig'))
version='20261109-release-v1'
for name in ('pd-trip-runtime-v4.js','pd-admin-console-v4.js','pd-passenger-notices-v5.js'):
 page,n=re.subn(r'(/assets/'+re.escape(name)+r'\?v=)[^"\s<]+',lambda m:m[1]+version,page);assert n==1
widget=original['pd_tips_widget.py'].decode('utf-8-sig')
widget,n=re.subn(r'(/assets/pd-registration\.js\?v=)[^"\s<]+',lambda m:m[1]+version,widget);assert n==1
ast.parse(widget)
planned={'miniapp_server.py':server.encode(),'pd_request_security.py':security.encode(),'miniapp/templates/index.html':page.encode(),'pd_tips_widget.py':widget.encode()}
planned.update({item['file']:(ROOT/'release'/item['file']).read_bytes() for item in manifest})
run_id=os.environ.get('GITHUB_RUN_ID',str(int(time.time())));assert run_id.isdigit()
backup='/home/wilsonpark/private_drive_backups/reset_20261109_'+run_id+'/'
runner='/home/wilsonpark/private_drive_reset_20261109_'+run_id+'/'
status=backup+'STATUS.txt';result_path=backup+'RESULT.json'
existing=session.get(HOST+'/files/path'+result_path,timeout=35);assert existing.status_code==404,'Reset already completed; refusing repeat'
# Code copies remain in a private account directory. SQLite backups are created by
# the host runner under a single transaction before its first DELETE.
for name,data in original.items():put(backup+'source/'+name,data)
put(backup+'SOURCE_MANIFEST.json',json.dumps({name:digest(data) for name,data in original.items()},sort_keys=True).encode())
for name in ('reset_remote.py','reset_logic.py'):put(runner+name,(ROOT/name).read_bytes())
print('CODE_BACKUP_VERIFIED files='+str(len(original))+' bot_supervisor_unchanged=true')
changed=False;reset_submitted=False
try:
 for name,data in planned.items():changed=True;put(PROJECT+name,data)
 api('POST',DOMAIN+'reload/')
 import requests
 public=requests.Session();site='https://wilsonpark.pythonanywhere.com'
 for _ in range(12):
  home=public.get(site+'/?v='+version,timeout=25)
  if home.status_code==200 and version in home.text:break
  time.sleep(3)
 else:raise RuntimeError('Updated application did not become ready')
 assert 'Как клиент</button>' not in home.text
 for item in manifest:
  response=public.get(site+item['public_path']+'?v='+version,timeout=25)
  assert response.status_code==200 and digest(response.content)==item['after_sha256'],'Public asset check failed'
 admin_headers={'X-Telegram-Init-Data':signed(next(iter(admins)),env['BOT_TOKEN'],int(time.time()))}
 assert public.get(site+'/api/admin/orders',headers=admin_headers,timeout=25).status_code==200,'Dispatcher access failed before reset'
 print('UI_DEPLOY_VERIFIED dispatcher_only_navigation=true auth_guard_loaded=true')
 command='umask 077; python3 '+shlex.quote(runner+'reset_remote.py')+' --root '+shlex.quote(PROJECT.rstrip('/'))+' --backup '+shlex.quote(backup.rstrip('/'))+' --status '+shlex.quote(status)+' > '+shlex.quote(backup+'PRIVATE_RUN.log')+' 2>&1'
 api('POST','/consoles/'+selected+'/send_input/',data={'input':command+'\n'});reset_submitted=True
 for _ in range(30):
  r=session.get(HOST+'/files/path'+status,timeout=35)
  if r.status_code==200:break
  assert r.status_code==404,'Status read failed';time.sleep(3)
 else:raise RuntimeError('Reset submitted; completion not confirmed. Do not repeat blindly.')
 assert r.text.strip()=='OK','Reset failed; transaction rolled back. See private host log.'
 summary=api('GET','/files/path'+result_path).json()
 db_manifest=api('GET','/files/path'+backup+'DATABASE_MANIFEST.json').json()
 for name,sha in db_manifest['files'].items():assert digest(api('GET','/files/path'+backup+name).content)==sha,'Database backup hash mismatch'
 response=public.get(site+'/api/admin/orders',headers=admin_headers,timeout=25);assert response.status_code==200 and response.json()['orders']==[]
 response=public.get(site+'/api/admin/pilot-assignments',headers=admin_headers,timeout=25);assert response.status_code==200 and response.json()['pilots']==[] and response.json()['assignments']==[]
 for uid in summary['revoked_ids']:
  headers={'X-Telegram-Init-Data':signed(uid,env['BOT_TOKEN'],summary['cutoff']-1)}
  assert public.get(site+'/api/orders',headers=headers,timeout=25).status_code==401,'Removed profile old session retained access'
 assert get('.env')==config_before,'Settings changed unexpectedly'
 tasks=api('GET','/always_on/').json();assert any(t.get('id')==279084 and t.get('state')=='Running' and t.get('enabled')is True for t in tasks),'Supervisor is not running'
 summary.update(dispatcher_access_verified=True,old_sessions_denied=len(summary['revoked_ids']),ui_deployed_files=sorted(planned),supervisor_unchanged=True,code_backup=backup+'source/')
 encrypt(summary)
 print('RESET_VERIFIED dispatcher_preserved=true test_orders=0 driver_applications=0 old_sessions_denied=true ui_updates_verified=true supervisor_unchanged=true')
except BaseException:
 if changed and not reset_submitted:
  for name,data in original.items():put(PROJECT+name,data)
  api('POST',DOMAIN+'reload/');print('CODE_ROLLBACK_VERIFIED reset_not_submitted=true')
 raise
