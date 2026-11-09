"""PRIVATE DRIVE: first choose language, then role, then registration.
Guarded one-template-only production patch. No database, order, payment, auth or CSS changes.
Preflight Jinja/JS + isolated transition tests, exact live SHA, verified private backup,
public smoke check and automatic source rollback.
"""
import hashlib,json,os,re,subprocess,tempfile,time
from pathlib import Path
import requests
from jinja2 import Environment

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com/"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
EXPECTED_SHA="ab5d9d4d923bccafe891ec54838e9ca923f7bc5a1e5a1a154aa3d65125e8906a"
VERSION="language-before-role-v1-20261109"
OLD_START=""" let chosen=false;try{chosen=['ru','lt','en'].includes(localStorage.getItem('pdOnboardingLanguage'))}catch(_){}
 const restored=pdObRead('pdOnboardingStage');pdShowOnboarding(!chosen?'language':['passenger','driver','role'].includes(restored)?restored:'role');"""
NEW_START=""" // For an incomplete registration, language is always the initial screen on opening.
 // Only an explicit language choice may advance to role (also across language reloads).
 const pendingAt=Number(pdObRead('pdWelcomeRoleAfterLanguageAt')||0);
 pdObStore('pdWelcomeRoleAfterLanguageAt',null);
 if(pendingAt>0&&Date.now()>=pendingAt&&Date.now()-pendingAt<300000)window.pdWelcomeRoleAdvanced=true;
 const restored=pdObRead('pdOnboardingStage');
 pdShowOnboarding(window.pdWelcomeRoleAdvanced&&['role','passenger','driver'].includes(restored)?restored:window.pdWelcomeRoleAdvanced?'role':'language');"""
OLD_CONTINUE=""" window.pdWelcomeContinue=function(manual){
   try{localStorage.setItem('pdOnboardingLanguage',selected)}catch(_){}
   pdObStore('pdOnboardingStage','passenger');
   if(manual)pdObStore('pdWelcomeManualPending','yes');
   if(selected!==window.PD_LANG){pdSwitchLanguage(selected);return}
   pdShowOnboarding('passenger');
   if(manual){
      const d=document.getElementById('pdRegistrationManual');
      if(d)d.open=true;
   }
 };"""
NEW_CONTINUE=""" window.pdWelcomeContinue=function(manual){
   try{localStorage.setItem('pdOnboardingLanguage',selected)}catch(_){}
   pdObStore('pdOnboardingStage','role');
   pdObStore('pdWelcomeManualPending',manual?'yes':null);
   window.pdWelcomeRoleAdvanced=true;
   if(selected!==window.PD_LANG){
      pdObStore('pdWelcomeRoleAfterLanguageAt',String(Date.now()));
      pdSwitchLanguage(selected);return;
   }
   pdObStore('pdWelcomeRoleAfterLanguageAt',null);
   pdShowOnboarding('role');
 };"""
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I)
token="".join(token.split())
if not token:raise RuntimeError("PythonAnywhere credentials not available")
s=requests.Session();s.headers["Authorization"]="Token "+token
if s.get(BASE+"/cpu/",timeout=35).status_code!=200:
    raise RuntimeError("PythonAnywhere API authentication failed")
last_call=0.
def api(method,path,**kwargs):
    global last_call
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last_call)))
        last_call=time.monotonic()
    for attempt in range(3):
        r=s.request(method,BASE+path,timeout=45,**kwargs)
        if r.status_code==429 and attempt<2:
            time.sleep(12*(attempt+1));continue
        if not r.ok:raise RuntimeError("Hosting "+method+" failed HTTP "+str(r.status_code))
        return r
def read(path):return api("GET","/files/path"+path).content
def write(path,data):
    api("POST","/files/path"+path,files={"content":("private-drive-language-order",data,"text/plain")})
    if read(path)!=data:raise RuntimeError("Remote file readback failed")
def sha(data):return hashlib.sha256(data).hexdigest()

original=read(ROOT+FILE)
if sha(original)!=EXPECTED_SHA:
    raise RuntimeError("LIVE_TEMPLATE_CHANGED no writes, hash="+sha(original)[:18])
html=original.decode("utf-8-sig")
for label,old in (("first launch",OLD_START),("welcome Continue",OLD_CONTINUE)):
    if html.count(old)!=1:
        raise RuntimeError("Unexpected "+label+" code structure; no writes")
patched=html.replace(OLD_START,NEW_START,1).replace(OLD_CONTINUE,NEW_CONTINUE,1)
assert patched.count('id="pdObLanguage"')==html.count('id="pdObLanguage"')==1
assert patched.count('id="pdObRole"')==html.count('id="pdObRole"')==1
assert patched.count('id="pdWelcomeTelegram"')==html.count('id="pdWelcomeTelegram"')==1
assert all(x in patched for x in ["private-drive-official-logo.jpeg","private-drive-night.png","pdRegisterPassengerTelegram()","🇱🇹","🇬🇧","🇷🇺"])
assert patched.count("pdShowOnboarding('role');")>=html.count("pdShowOnboarding('role');")
Environment().parse(patched)
# Compile all inline JS scripts that do not contain Jinja expression delimiters.
scripts=re.findall(r'<script\b[^>]*>([\s\S]*?)</script>',patched)
with tempfile.TemporaryDirectory() as td:
    for i,js in enumerate(scripts):
        if not js.strip() or "{{" in js or "{%" in js: continue
        p=Path(td)/(str(i)+".js");p.write_text(js,encoding="utf-8")
        run=subprocess.run(["node","--check",str(p)],capture_output=True,text=True)
        if run.returncode:
            raise RuntimeError("Inline JavaScript syntax failed on block "+str(i)+": "+run.stderr[-230:])
    # Separate pure VM test using function extracts, fake guest/staff and fake local storage.
    probe=Path(td)/"probe.json"
    probe.write_text(json.dumps({"start":re.search(r"function pdOnboardingStart\(user\)\{[\s\S]*?\n\}",patched).group(),
        "welcome":patched.split("window.pdWelcomeContinue=function(manual){",1)[1].split("\n };",1)[0]}),encoding="utf-8")
    vmtest=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const raw=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let state={},shown=[],switches=[],hidden=0,pilot=0;
const ctx={window:{PD_LANG:'ru'},Date,console,
  pdObRead:k=>state[k]||null,pdObStore:(k,v)=>{if(v===null)delete state[k];else state[k]=v},
  pdShowOnboarding:v=>shown.push(v),pdHideOnboarding:()=>hidden++,pdEnterPilot:()=>pilot++,
  pdApplyRoleAccess:()=>{},localStorage:{setItem(){}}
};
vm.createContext(ctx);
vm.runInContext(raw.start,ctx);
ctx.pdOnboardingStart({registered:false});
assert.equal(shown.at(-1),'language','Guest must see language first');
shown=[];state.pdOnboardingStage='role';ctx.pdOnboardingStart({registered:false});
assert.equal(shown.at(-1),'language','Remembered role must not skip initial language');
shown=[];state.pdWelcomeRoleAfterLanguageAt=String(Date.now());state.pdOnboardingStage='role';
ctx.pdOnboardingStart({registered:false});
assert.equal(shown.at(-1),'role','After chosen language + reload show role');
assert.equal(state.pdWelcomeRoleAfterLanguageAt,undefined,'One-shot marker must clear');
ctx.pdOnboardingStart({registered:true,name:'existing',phone:'+37060000000'});
assert.equal(hidden,1,'Existing registered user stays signed in');
ctx.pdOnboardingStart({pilot_access:true});assert.equal(pilot,1,'Pilots unaffected');
ctx.pdOnboardingStart({admin:true});assert.equal(hidden,2,'Admins unaffected');
const c=raw.welcome;
const w=Object.assign({pdSwitchLanguage:v=>switches.push(v),document:{getElementById:()=>({open:false})}},ctx);
vm.runInContext("window.pdWelcomeContinue=function(manual){"+c+"\n };",ctx);
ctx.pdWelcomeContinue(true);
assert.equal(shown.at(-1),'role','Continue must show role before registration');
assert.equal(state.pdWelcomeManualPending,'yes');
ctx.window.PD_LANG='ru';
ctx.pdWelcomeContinue(false);assert.equal(state.pdWelcomeManualPending,undefined);
console.log('PASS guest language first, persisted old role ignored, chosen language -> role, staff preservation, manual link');
"""
    v=Path(td)/"probe.cjs";v.write_text(vmtest,encoding="utf-8")
    tested=subprocess.run(["node",str(v),str(probe)],capture_output=True,text=True)
    if tested.returncode:raise RuntimeError("Offline transition test failed: "+tested.stderr[-600:])
    print("OFFLINE_FLOW_TESTS_PASS",tested.stdout.strip(),flush=True)
print("LANGUAGE_ROLE_PREFLIGHT_PASS Jinja=true JS=true handlers_unchanged=true registration_untouched=true",flush=True)
if os.environ.get("PD_FIRST_LANGUAGE_DEPLOY")!="1":
    print("LANGUAGE_ROLE_DRY_RUN_PASS hosting_writes=0",flush=True)
    raise SystemExit(0)

runid=os.environ.get("GITHUB_RUN_ID","")
if not runid.isdigit():raise RuntimeError("Run ID missing")
backup=f"/home/wilsonpark/private_drive_backups/first_language_role_20261109_{runid}/"
write(backup+FILE,original)
write(backup+"SOURCE_MANIFEST.json",json.dumps({"file":FILE,"sha256":sha(original),"bytes":len(original)}).encode())
print("LANGUAGE_ROLE_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=original:raise RuntimeError("Concurrent change detected; deployment blocked")
changed=False
try:
    changed=True
    write(ROOT+FILE,patched.encode("utf-8"))
    api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    success=False
    for attempt in range(8):
        r=requests.get(SITE,params={"first_language_role":VERSION,"n":str(attempt)},
            headers={"Cache-Control":"no-cache"},timeout=30)
        success=(r.status_code==200 and NEW_START in r.text and NEW_CONTINUE in r.text and
            'id="pdObLanguage"' in r.text and 'id="pdObRole"' in r.text and
            'id="pdWelcomeTelegram"' in r.text)
        print("PUBLIC_FLOW_SMOKE",attempt,"http",r.status_code,"verified",success,flush=True)
        if success:break
        time.sleep(4)
    if not success:raise RuntimeError("Public flow smoke verification failed")
    print("LANGUAGE_BEFORE_ROLE_LIVE_VERIFIED HTTP=200 first_screen_language=true next_screen_role=true orders_unchanged=true",flush=True)
except BaseException:
    if changed:
        write(ROOT+FILE,original)
        api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        print("LANGUAGE_ROLE_ROLLBACK_VERIFIED",flush=True)
    raise
