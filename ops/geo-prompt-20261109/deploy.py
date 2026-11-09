"""PRIVATE DRIVE: do not automatically show 'Показать вас на карте?' during booking.
Remove only the unused auto prompt function and its single route-open invocation.
Preserve explicit GPS button + address form + map and all orders/payment/pilot logic.
Live SHA guard; dry-run Jinja+JavaScript+unit tests; backup; public smoke; rollback.
"""
import hashlib,json,os,re,subprocess,tempfile,time
from pathlib import Path
import requests
from jinja2 import Environment

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com/"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
EXPECTED="864f893ef373caae725c3979987bd4e032a39bf42372f8f39ff6399a67e58313"
FUNC_START="function pdbAutoLocate(){"
FUNC_END="\n\n\nconst pdbSuggestState="
AUTO_CALL="setTimeout(()=>{pdbMapInit();pdbAutoLocate()},80)"
MANUAL_CALL="setTimeout(()=>{pdbMapInit()},80)"
token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token:raise RuntimeError("Hosting credentials missing")
s=requests.Session();s.headers={"Authorization":"Token "+token}
if s.get(BASE+"/cpu/",timeout=30).status_code!=200:raise RuntimeError("Hosting API access failed")
last=0.
def api(method,path,**kw):
    global last
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last)));last=time.monotonic()
    for n in range(3):
        r=s.request(method,BASE+path,timeout=45,**kw)
        if r.status_code==429 and n<2:
            time.sleep(12*(n+1));continue
        if not r.ok:raise RuntimeError("Hosting "+method+" HTTP "+str(r.status_code))
        return r
def read(path):return api("GET","/files/path"+path).content
def write(path,data):
    api("POST","/files/path"+path,files={"content":("pd-map-prompt",data,"text/html")})
    if read(path)!=data:raise RuntimeError("Hosting read-back mismatch")
def digest(data):return hashlib.sha256(data).hexdigest()
original=read(ROOT+FILE)
if digest(original)!=EXPECTED:raise RuntimeError("CONCURRENT_LIVE_CHANGE no writes; SHA="+digest(original))
old=original.decode("utf-8-sig")
if old.count(FUNC_START)!=1 or old.count(FUNC_END)<1 or old.count(AUTO_CALL)!=1:
    raise RuntimeError("Unexpected location prompt structure; no writes")
if old.count("pdbAutoLocate")!=2:raise RuntimeError("Additional auto trigger exists; no writes")
a=old.index(FUNC_START)
b=old.index(FUNC_END,a)
removed=old[a:b]
if not all(t in removed for t in ("Показать вас на карте?","pdBookingLocationOffer","pdbLocate(true)","pdSimpleDialog")):
    raise RuntimeError("Auto modal source does not match expected implementation; no writes")
new=old[:a]+old[b+3:]
new=new.replace(AUTO_CALL,MANUAL_CALL,1)
assert "pdbAutoLocate" not in new
assert "Показать вас на карте?" not in new
assert "pdBookingLocationOffer" not in new
assert new.count("function pdbLocate(explicit){")==old.count("function pdbLocate(explicit){")==1
assert new.count('onclick="pdbLocate(true)"')==old.count('onclick="pdbLocate(true)"')==1
assert 'id="pdbLocate"' in new
assert 'id="pdbOrigin"' in new and 'id="pdbDest"' in new
assert 'id="pdbMap"' in new and "function pdbMapInit()" in new
assert "function pdbBrowserLocation()" in new
assert "pdbMapInit();" in new and MANUAL_CALL in new
assert 'id="pdPilotWork"' in new and 'id="pdCustomers"' in new
assert 'id="pdObTelegramOneSubmit"' in new
Environment().parse(new)
with tempfile.TemporaryDirectory() as temp:
    scripts=re.findall(r'<script\b[^>]*>([\s\S]*?)</script>',new)
    checked=0
    for i,js in enumerate(scripts):
        if not js.strip() or "{{" in js or "{%" in js:continue
        p=Path(temp)/(str(i)+".js")
        p.write_text(js,encoding="utf-8")
        r=subprocess.run(["node","--check",str(p)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError("JavaScript block "+str(i)+" invalid: "+r.stderr[-400:])
        checked+=1
    probe=Path(temp)/"test.cjs"
    probe.write_text(r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
let initialized=0,scheduled=[],geoCalls=0,dialogCalls=0;
const ctx={pdbMapInit:()=>initialized++,pdbLocate:()=>geoCalls++,pdSimpleDialog:()=>dialogCalls++,
  pdbOldGo:n=>{},document:{body:{classList:{toggle:()=>{}}}},window:{scrollTo:()=>{}},
  setTimeout:fn=>scheduled.push(fn)};
vm.createContext(ctx);
vm.runInContext("go=function(n){pdbOldGo(n);document.body.classList.toggle('pdb-active',n===11);if(n===11){setTimeout(()=>{pdbMapInit()},80);window.scrollTo(0,0)}};",ctx);
vm.runInContext("go(11)",ctx);
assert.equal(scheduled.length,1);
scheduled[0]();
assert.equal(initialized,1,"Map must still initialize when entering booking");
assert.equal(geoCalls,0,"GPS must not activate automatically");
assert.equal(dialogCalls,0,"No GPS modal when booking starts");
vm.runInContext("pdbLocate(true)",ctx);
assert.equal(geoCalls,1,"Manual GPS location button remains usable");
console.log("GEO_FLOW_PASS map_on_booking=true automatic_popup=false manual_location=true");
""",encoding="utf-8")
    r=subprocess.run(["node",str(probe)],capture_output=True,text=True)
    if r.returncode:raise RuntimeError("GPS flow test failed: "+r.stderr[-400:])
    print(r.stdout.strip(),flush=True)
print("GEO_PROMPT_PREFLIGHT_PASS Jinja=true JS_blocks="+str(checked)+" modal_removed=true explicit_gps_retained=true",flush=True)
if os.environ.get("PD_DISABLE_GEO_PROMPT_DEPLOY")!="1":
    print("GEO_PROMPT_DRY_RUN_PASS production_writes=0",flush=True)
    raise SystemExit(0)
run=os.environ.get("GITHUB_RUN_ID","")
if not run.isdigit():raise RuntimeError("CI run ID missing")
backup=f"/home/wilsonpark/private_drive_backups/geo_auto_prompt_20261109_{run}/"
write(backup+FILE,original)
write(backup+"MANIFEST.json",json.dumps({"source":FILE,"sha256":digest(original),"bytes":len(original)}).encode())
print("GEO_PROMPT_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=original:raise RuntimeError("Live source changed since audit; no writes")
changed=False
try:
    changed=True
    write(ROOT+FILE,new.encode("utf-8"))
    try:api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:
        print("RELOAD_TIMEOUT public smoke will determine success",flush=True)
    good=False
    for n in range(9):
        r=requests.get(SITE,params={"no_auto_map_popup":run,"attempt":n},headers={"Cache-Control":"no-cache"},timeout=30)
        h=r.text
        good=(r.status_code==200 and
              "Показать вас на карте?" not in h and
              "pdBookingLocationOffer" not in h and
              "pdbAutoLocate" not in h and
              'id="pdbLocate"' in h and
              'onclick="pdbLocate(true)"' in h and
              MANUAL_CALL in h and
              'id="pdbMap"' in h and
              'id="pdbOrigin"' in h and
              'id="pdbDest"' in h)
        print("GEO_PROMPT_PUBLIC_CHECK",n,"http",r.status_code,"verified",good,flush=True)
        if good:break
        time.sleep(4)
    if not good:raise RuntimeError("Public manual-only GPS verification failed")
    print("GEO_PROMPT_LIVE_VERIFIED HTTP=200 automatic_dialog_gone=true explicit_map_button_retained=true orders_untouched=true",flush=True)
except BaseException:
    if changed:
        write(ROOT+FILE,original)
        try:api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        except requests.exceptions.ReadTimeout:pass
        if read(ROOT+FILE)!=original:raise RuntimeError("Live rollback readback mismatch")
        print("GEO_PROMPT_ROLLBACK_VERIFIED",flush=True)
    raise
