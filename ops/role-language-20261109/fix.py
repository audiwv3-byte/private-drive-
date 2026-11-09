"""PRIVATE DRIVE: remove only duplicated 'Язык' button under role choices.
The top-right language selector, onboarding transitions, orders, user data, and
payments are unchanged. Source backup + exact readback + reload + rollback.
"""
import hashlib,json,os,re,time
import requests
from jinja2 import Environment

ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com/"
TARGET='<button type="button" class="secondary" onclick="pdShowOnboarding(\'language\')">Язык</button>'
ROLE_START='<div id="pdObRole" class="hidden">'
ROLE_END='<form id="pdObPassenger"'
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I)
token="".join(token.split())
if not token:raise RuntimeError("Missing PythonAnywhere API credentials")
s=requests.Session();s.headers["Authorization"]="Token "+token
if s.get(API+"/cpu/",timeout=35).status_code!=200:
    raise RuntimeError("PythonAnywhere API access unavailable")
last_request=0
def api(method,path,**kwargs):
    global last_request
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last_request)))
        last_request=time.monotonic()
    for attempt in range(3):
        res=s.request(method,API+path,timeout=40,**kwargs)
        if res.status_code==429 and attempt<2:
            time.sleep(15*(attempt+1));continue
        if not res.ok:raise RuntimeError("Hosting API "+method+" failure HTTP "+str(res.status_code))
        return res
def read(path):return api("GET","/files/path"+path).content
def put(path,blob):
    api("POST","/files/path"+path,files={"content":("pd-role-language",blob,"text/plain")})
    if read(path)!=blob:raise RuntimeError("Remote readback did not match")
def hash256(data):return hashlib.sha256(data).hexdigest()
old=read(ROOT+FILE)
text=old.decode("utf-8-sig")
start=text.index(ROLE_START);end=text.index(ROLE_END,start)
role=text[start:end]
if role.count(TARGET)!=1:raise RuntimeError("Role language button not uniquely found; no writes")
if "pdShowOnboarding('passenger')" not in role or "pdShowOnboarding('driver')" not in role:
    raise RuntimeError("Role choices changed; no writes")
if "id=\"pdLangSelect\"" not in text:
    raise RuntimeError("Top language selector missing; no writes")
new_role=role.replace(TARGET,"",1)
new_page=text[:start]+new_role+text[end:]
assert len(new_page)==len(text)-len(TARGET)
assert new_page[:start]==text[:start] and new_page[start+len(new_role):]==text[end:]
assert "id=\"pdLangSelect\"" in new_page
assert "pdWelcomeContinue" in new_page and "pdShowOnboarding('passenger')" in new_role and "pdShowOnboarding('driver')" in new_role
assert new_role.count("Язык")==0
Environment().parse(new_page)
print("ROLE_LANGUAGE_PREFLIGHT_PASS original_sha256="+hash256(old)[:20],
      "bottom_language_removed=true top_right_language_retained=true",
      "role_buttons_retained=2 other_code_unchanged=true jinja=true",flush=True)
if os.environ.get("PD_ROLE_LANGUAGE_DEPLOY")!="1":
    print("ROLE_LANGUAGE_DRY_RUN_PASS production_writes=0",flush=True)
    raise SystemExit(0)
run=os.environ.get("GITHUB_RUN_ID","")
if not run.isdigit():raise RuntimeError("Missing CI run id")
backup=f"/home/wilsonpark/private_drive_backups/role_language_{run}/"
put(backup+FILE,old)
put(backup+"SOURCE_MANIFEST.json",json.dumps({"file":FILE,"sha256":hash256(old),"bytes":len(old)}).encode())
print("ROLE_LANGUAGE_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=old:
    raise RuntimeError("Concurrent production change before deployment; no writes")
changed=False
try:
    changed=True
    put(ROOT+FILE,new_page.encode("utf-8"))
    api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    successful=False
    for i in range(8):
        res=requests.get(SITE,params={"role_lang_fix":run,"attempt":i},
                         headers={"Cache-Control":"no-cache"},timeout=30)
        html=res.text
        rs=html.find(ROLE_START);re_=html.find(ROLE_END,rs)
        public_role=html[rs:re_] if rs>=0 and re_>rs else ""
        successful=(res.status_code==200 and TARGET not in public_role
                    and "id=\"pdLangSelect\"" in html
                    and "pdShowOnboarding('passenger')" in public_role
                    and "pdShowOnboarding('driver')" in public_role
                    and 'id="pdObLanguage"' in html
                    and 'id="pdWelcomeTelegram"' in html)
        print("ROLE_LANGUAGE_PUBLIC_SMOKE",i,"http",res.status_code,
              "bottom_language_absent",TARGET not in public_role,
              "top_language_retained","id=\"pdLangSelect\"" in html,
              "verified",successful,flush=True)
        if successful:break
        time.sleep(4)
    if not successful:raise RuntimeError("Public role language fix verification failed")
    print("ROLE_LANGUAGE_LIVE_VERIFIED HTTP=200 duplicate_removed=true top_right_language_working=true orders_unchanged=true",flush=True)
except BaseException:
    if changed:
        put(ROOT+FILE,old)
        api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        print("ROLE_LANGUAGE_SOURCE_ROLLBACK_VERIFIED",flush=True)
    raise
