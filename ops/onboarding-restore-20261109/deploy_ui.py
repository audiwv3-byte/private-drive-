"""Restore LIVE first-launch language chooser via PythonAnywhere files API.
Only three UI source files; no databases, orders, payments, settings or sessions.
Preflight exact observed fingerprints, private byte-for-byte backup, verified
readback, webapp reload, public smoke test, automatic source rollback on failure.
"""
import hashlib, json, os, re, sys, time
from pathlib import Path
import requests
USER="wilsonpark"
PROJECT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
DOMAIN="wilsonpark.pythonanywhere.com"
API=f"https://www.pythonanywhere.com/api/v0/user/{USER}"
SITE="https://"+DOMAIN
FILES=["miniapp/templates/index.html","pd_registration.js","pd_tips_widget.py"]
EXPECTED={
 "miniapp/templates/index.html":"711e67223dadc6d7dabd",
 "pd_registration.js":"e34583bd267c041d7e35",
 "pd_tips_widget.py":"62382f14b3c669a34e6c",
}
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I)
token="".join(token.split())
assert token, "PA_API_TOKEN unavailable"
s=requests.Session()
s.headers["Authorization"]="Token "+token
assert s.get(API+"/cpu/",timeout=35).status_code==200,"Hosting API credentials unavailable"
last_file_call=0.0
def call(method,path,**args):
  global last_file_call
  if path.startswith('/files/path'):
    time.sleep(max(0.0,1.65-(time.monotonic()-last_file_call)))
    last_file_call=time.monotonic()
  for retry in range(4):
    r=s.request(method,API+path,timeout=40,**args)
    if r.status_code==429 and retry<3:
      time.sleep(8*(retry+1));continue
    if not r.ok:raise RuntimeError("Hosting API "+method+" "+path.split("?")[0]+" HTTP "+str(r.status_code))
    return r
def digest(data):return hashlib.sha256(data).hexdigest()
def read(name):return call("GET","/files/path"+PROJECT+name).content
def put(path,data):
  call("POST","/files/path"+path,files={"content":("private-drive-ui",data,"application/octet-stream")})
  check=call("GET","/files/path"+path).content
  if check!=data:raise RuntimeError("Remote readback mismatch")
  return check
def sub_once(source,old,new,label):
  n=source.count(old)
  if n!=1:raise RuntimeError("Unexpected live source structure: "+label+" count="+str(n))
  return source.replace(old,new,1)

original={name:read(name) for name in FILES}
for name in FILES:
  h=digest(original[name])
  if not h.startswith(EXPECTED[name]):
    raise RuntimeError("LIVE_SOURCE_CHANGED "+name+" sha="+h[:16]+" - no writes performed")
print("LIVE_SOURCE_FINGERPRINTS_VERIFIED files=3")
page=original["miniapp/templates/index.html"].decode("utf-8-sig")
js=original["pd_registration.js"].decode("utf-8-sig")
widget=original["pd_tips_widget.py"].decode("utf-8-sig")
first=page.index('<div id="pdObLanguage"')
second=page.index('<div id="pdObRole"',first)
old_block=page[first:second]
assert 200<=len(old_block)<1800 and 'pdChooseInitialLanguage' in old_block,"Unexpected language chooser markup"
language='''<div id="pdObLanguage" class="hidden"><img class="pd-ob-hero-logo" src="/assets/private-drive-official-logo.jpeg" alt="PRIVATE DRIVE — фирменный логотип PD" width="180" height="180"><h1>Выберите язык</h1><p class="muted">Choose language · Pasirinkite kalbą</p><div class="pd-ob-language-options"><button type="button" lang="en" onclick="pdChooseInitialLanguage('en')"><span aria-hidden="true" class="pd-ob-flag">🇬🇧</span><span>English</span></button><button type="button" lang="lt" onclick="pdChooseInitialLanguage('lt')"><span aria-hidden="true" class="pd-ob-flag">🇱🇹</span><span>Lietuvių</span></button><button type="button" lang="ru" onclick="pdChooseInitialLanguage('ru')"><span aria-hidden="true" class="pd-ob-flag">🇷🇺</span><span>Русский</span></button></div><p class="muted">PRIVATE DRIVE · Литва и Европа</p></div>
'''
page=page[:first]+language+page[second:]
css='''<style id="pd-language-restore-20261109">
body.pd-onboarding-active[data-pd-onboarding-stage="language"] .pd-branded-header{display:none!important}
body.pd-onboarding-active[data-pd-onboarding-stage="language"]{background:radial-gradient(circle at 50% 15%,#352913,transparent 60%),#090a0b}
body.pd-onboarding-active #pdObLanguage:not(.hidden){text-align:center;max-width:620px;margin:5vh auto 20px;padding:30px 17px;border:1px solid #806a41;border-radius:22px;background:linear-gradient(160deg,#1b1916,#0c0d0e)}
#pdObLanguage .pd-ob-hero-logo{display:block;width:min(170px,45vw);height:auto;aspect-ratio:1;object-fit:contain;margin:0 auto 22px;filter:drop-shadow(0 6px 16px #0009)}
#pdObLanguage .pd-ob-language-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:20px 0}
#pdObLanguage .pd-ob-language-options button{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;min-width:0;min-height:100px;padding:13px 4px;background:#202020;border:1px solid #b28d4a;border-radius:16px;color:#f5dba7;font-size:14px}
#pdObLanguage .pd-ob-flag{font-size:39px;line-height:1.2}
.pd-registration-manual{border:1px solid #594b31;border-radius:12px;padding:10px 14px;margin:12px 0;clear:both}
.pd-registration-manual summary{color:#f4cb80;cursor:pointer}
.pd-registration-login{display:block!important;width:100%;min-height:57px;font-size:17px;margin:16px 0}
@media(max-width:400px){#pdObLanguage .pd-ob-language-options{gap:6px}#pdObLanguage .pd-ob-language-options button{font-size:12px}#pdObLanguage .pd-ob-flag{font-size:33px}}
</style>'''
page=sub_once(page,"</head>",css+"</head>","append-only restoration CSS")
old_override="const show=pdShowOnboarding;pdShowOnboarding=function(stage){const u=window.pdOnboardingUser;const guest=!u?.registered&&!u?.admin&&!u?.pilot_access;return show(guest&&(stage==='role'||stage==='language')?'passenger':stage)};"
new_override="const show=pdShowOnboarding;pdShowOnboarding=function(stage){const result=show(stage);document.body.dataset.pdOnboardingStage=stage;return result};"
js=sub_once(js,old_override,new_override,"remove auto-redirect from language/role to passenger registration")
initial=re.compile(r"if\(!form\.classList\.contains\('hidden'\)\|\|\['pdObRole','pdObLanguage'\]\.some\(id=>!document\.getElementById\(id\)\?\.classList\.contains\('hidden'\)\)\)pdShowOnboarding\('passenger'\);")
js,count=initial.subn("if(!document.getElementById('pdObLanguage')?.classList.contains('hidden'))document.body.dataset.pdOnboardingStage='language';",js)
if count!=1:raise RuntimeError("Unexpected script auto-entry pattern; no writes performed")
# Keep current registration fields/consents but make Telegram the prominent first action.
# The existing labels and submit button remain available under an expandable manual fallback.
upgrade='''\n// Restore Telegram-first onboarding without bypassing legal/phone consent.
(()=>{
 const primary=form.querySelector('[onclick="pdRegisterPassengerTelegram()"]');
 const title=form.querySelector('h1');
 if(!primary||!title)throw Error('Expected passenger registration controls missing');
 title.after(primary);
 primary.classList.add('pd-registration-login');
 const details=document.createElement('details');details.id='pdRegistrationManual';details.className='pd-registration-manual';
 const summary=document.createElement('summary');
 summary.textContent=t('Ввести имя и номер вручную','Enter details manually','Įvesti duomenis rankiniu būdu');
 details.append(summary);
 const fields=[
   form.querySelector('label[for="pdObPassengerName"]'),document.getElementById('pdObPassengerName'),
   form.querySelector('label[for="pdObPassengerPhone"]'),document.getElementById('pdObPassengerPhone'),
   form.querySelector('label[for="pdObPassengerEmail"]'),document.getElementById('pdObPassengerEmail'),
   form.querySelector('.actions button[type="submit"]')
 ];
 for(const el of fields)if(el)details.append(el);
 primary.after(details);
 // The original consents and driver entry remain accessible.
 if(!form.classList.contains('hidden')&&!document.getElementById('pdObLanguage')?.classList.contains('hidden'))details.open=false;
})();
'''
assert js.endswith("})();\n") or js.endswith("})();"),"Unexpected registration script end"
ix=js.rfind("})();")
js=js[:ix]+upgrade+js[ix:]
# Existing cache-busting query is changed only for the registration source.
widget,count=re.subn(r'(/assets/pd-registration\.js\?v=)[^"\s<>]+',r'\g<1>20261109-language-restore-v1',widget)
if count!=1:raise RuntimeError("Could not locate unique registration script version marker")
updated={
 "miniapp/templates/index.html":page.encode("utf-8"),
 "pd_registration.js":js.encode("utf-8"),
 "pd_tips_widget.py":widget.encode("utf-8"),
}
assert "guest&&(stage==='role'||stage==='language')?'passenger':stage" not in js
assert all(flag in page for flag in ("🇬🇧","🇱🇹","🇷🇺"))
assert all(data!=original[name] for name,data in updated.items())
print("PATCH_PREFLIGHT_PASS flags=3 telegram_first=true manual_fallback=true no_data_migrations=true")
if os.environ.get("PD_UI_DEPLOY")!="1":
  print("DRY_RUN_PASS no_remote_writes=true")
  raise SystemExit(0)
run=os.environ.get("GITHUB_RUN_ID","")
assert run.isdigit(),"Missing CI run ID"
backup="/home/wilsonpark/private_drive_backups/onboarding_restore_20261109_"+run+"/"
for name,data in original.items():put(backup+"source/"+name,data)
manifest={name:digest(data) for name,data in original.items()}
put(backup+"SOURCE_MANIFEST.json",json.dumps(manifest,sort_keys=True).encode())
print("SOURCE_BACKUP_VERIFIED",backup,"files=3")
# Double-check no concurrent changes occurred during backup.
for name,data in original.items():
  if read(name)!=data:raise RuntimeError("Remote source changed during backup; no application files were written")
changed=[]
try:
  for name,data in updated.items():
    changed.append(name)
    put(PROJECT+name,data)
  call("POST","/webapps/"+DOMAIN+"/reload/")
  public=requests.Session()
  okay=False
  for attempt in range(7):
    r=public.get(SITE+"/?pd_restore_verification="+run,timeout=25,headers={"Cache-Control":"no-cache"})
    f=public.get(SITE+"/assets/pd-registration.js?v=20261109-language-restore-v1",timeout=25,headers={"Cache-Control":"no-cache"})
    visible=all(flag in r.text for flag in ("🇬🇧","🇱🇹","🇷🇺"))
    script_ok=digest(f.content)==digest(updated["pd_registration.js"])
    print("PUBLIC_SMOKE_CHECK",attempt,"page_http",r.status_code,"page_bytes",len(r.content),"page_flags",visible,"script_http",f.status_code,"script_bytes",len(f.content),"script_hash",digest(f.content)[:20],"expected_script_hash",digest(updated["pd_registration.js"])[:20],flush=True)
    if r.status_code==200 and f.status_code==200 and visible and script_ok:
      okay=True;break
    time.sleep(4)
  if not okay:raise RuntimeError("Public page/script verification failed")
  print("LIVE_UI_RESTORED_AND_VERIFIED flags=3 custom_logo=true login_primary=true")
  print("REMOTE_BACKUP_LOCATION",backup)
  print("ORDERS_PAYMENTS_DATABASES_UNCHANGED true")
except BaseException as e:
  for name in reversed(changed):
    put(PROJECT+name,original[name])
  if changed:call("POST","/webapps/"+DOMAIN+"/reload/")
  print("UI_SOURCE_ROLLBACK_VERIFIED changed_files="+str(len(changed)))
  raise
