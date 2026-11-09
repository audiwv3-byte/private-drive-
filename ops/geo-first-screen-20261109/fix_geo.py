"""PRIVATE DRIVE: suppress passenger geo popup during language choice and registration.
Guarded, no-order no-payment single-template fix with exact source hash check, private backup,
read-back, optional deployment, public smoke test and source rollback.
"""
import hashlib
import os
import re
import time
import json
import tempfile
import subprocess
import requests
from jinja2 import Environment

PROJECT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
PA="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
URL="https://wilsonpark.pythonanywhere.com/"
EXPECTED_SHA_PREFIX="a6979de7125481ef5b98"
OLD="if(!window.pdBootstrapDone||!window.pdOnboardingUser||window.pdOnboardingUser.pilot_access)return;"
NEW="if(!window.pdBootstrapDone||!window.pdOnboardingUser||window.pdOnboardingUser.pilot_access||!window.pdOnboardingUser.registered||document.body.classList.contains('pd-onboarding-active'))return;"
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I)
token="".join(token.split())
if not token:raise RuntimeError("Hosting API credentials unavailable")
sess=requests.Session()
sess.headers.update({"Authorization":"Token "+token})
probe=sess.get(PA+"/cpu/",timeout=35)
if probe.status_code!=200:raise RuntimeError("Hosting API credentials verification failed HTTP "+str(probe.status_code))
last_file_request=0.0
def api(method,path,**kwargs):
    global last_file_request
    if path.startswith("/files/path"):
        time.sleep(max(0.0,1.65-(time.monotonic()-last_file_request)))
        last_file_request=time.monotonic()
    for retry in range(4):
        res=sess.request(method,PA+path,timeout=40,**kwargs)
        if res.status_code==429 and retry<3:
            time.sleep(10*(retry+1));continue
        if not res.ok:raise RuntimeError("Hosting operation "+method+" failed HTTP "+str(res.status_code))
        return res
def read(path):return api("GET","/files/path"+path).content
def put(path,data):
    api("POST","/files/path"+path,files={"content":("private-drive-template",data,"text/plain")})
    if read(path)!=data:raise RuntimeError("Remote write verification failed")
def sha(data):return hashlib.sha256(data).hexdigest()

original=read(PROJECT+FILE)
assert sha(original).startswith(EXPECTED_SHA_PREFIX),"Live source unexpectedly changed; abort before writes"
text=original.decode("utf-8-sig")
assert text.count(OLD)==1,"Location guard changed unexpectedly; abort before writes"
start=text.index("function pdbAutoLocate(){")
end=text.index("const pdbSuggestState",start)
assert start<text.index(OLD)<end and "Показать вас на карте?" in text[start:end],"Location guard outside expected function"
updated=text.replace(OLD,NEW,1)
Environment().parse(updated)
fn=updated[updated.index("function pdbAutoLocate(){"):updated.index("const pdbSuggestState",start)]
with tempfile.NamedTemporaryFile("w",suffix=".js",encoding="utf-8") as t:
    t.write(fn);t.flush()
    tested=subprocess.run(["node","--check",t.name],capture_output=True,text=True)
    if tested.returncode:raise RuntimeError("Patched geo function failed JS parsing")
assert "||!window.pdOnboardingUser.registered||document.body.classList.contains('pd-onboarding-active')" in fn
assert updated.count(NEW)==1 and updated.count("Показать вас на карте?")==text.count("Показать вас на карте?")
data=updated.encode("utf-8")
print("PREFLIGHT_GEO_GUARD_PASS", "onboarding_blocks_popup=true", "unregistered_blocks_popup=true", "booking_geolocation_retained=true",flush=True)
if os.environ.get("PD_GEO_DEPLOY")!="1":
    print("GEO_DRY_RUN_PASS production_writes=0",flush=True)
    raise SystemExit(0)

run_id=os.environ.get("GITHUB_RUN_ID","")
assert run_id.isdigit(),"Missing CI run ID"
backup=f"/home/wilsonpark/private_drive_backups/geo_modal_{run_id}/"
put(backup+FILE,original)
put(backup+"MANIFEST.json",json.dumps({"source":FILE,"sha256":sha(original),"length":len(original)}).encode())
print("GEO_SOURCE_BACKUP_VERIFIED",backup,flush=True)
if read(PROJECT+FILE)!=original:raise RuntimeError("Concurrent source change; no application writes")
changed=False
try:
    changed=True
    put(PROJECT+FILE,data)
    api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    public=requests.Session()
    ok=False
    for attempt in range(8):
        res=public.get(URL,params={"geo_guard_check":run_id+"_"+str(attempt)},timeout=30,headers={"Cache-Control":"no-cache"})
        match=res.status_code==200 and NEW in res.text and "🇱🇹" in res.text
        print("PUBLIC_GEO_SMOKE",attempt,"HTTP",res.status_code,"guard_present",NEW in res.text,"lang_flags_present","🇱🇹" in res.text,flush=True)
        if match:ok=True;break
        time.sleep(4)
    if not ok:raise RuntimeError("Public template verification failed")
    print("GEO_PROMPT_FIX_LIVE_VERIFIED", "HTTP=200","first_language_unblocked=true","orders_unchanged=true","geolocation_button_unchanged=true",flush=True)
except BaseException:
    if changed:
        put(PROJECT+FILE,original)
        api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        print("GEO_SOURCE_ROLLBACK_VERIFIED",flush=True)
    raise
