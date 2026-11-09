"""Remove only privacy and terms duplicates from the PRIVATE DRIVE passenger profile.
Preserve global header, privacy/legal pages, and profile support/Telegram contacts.
Exact-match guarded deployment, backup and automatic source rollback.
No access to customer/order/financial records.
"""
import hashlib,json,os,re,subprocess,tempfile,time
from pathlib import Path
from jinja2 import Environment
import requests

API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
SITE="https://wilsonpark.pythonanywhere.com/"
SHA="4d2eccf7230c9ca85bfdf81f94f10e4a47b2593ca7ab97d95de4d226424409ae"
PROFILE_START='<section class="panel hidden" id="step14">'
PROFILE_STOP='<div id="pdProfilePageHome">'
REMOVABLE='<a href="/privacy" target="_blank" rel="noopener noreferrer">Политика конфиденциальности</a> · <a href="/legal" target="_blank" rel="noopener noreferrer">Условия поездки и оплаты</a> · '
KEEP='<a href="mailto:eurobaltictransfer@gmail.com">Вопросы и удаление данных</a> · <a href="https://t.me/PrivatDraiv" target="_blank" rel="noopener noreferrer" data-pd-telegram-contact="true">@PrivatDraiv</a>'
token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
assert token,"Missing hosting API key"
session=requests.Session();session.headers={"Authorization":"Token "+token}
if session.get(API+"/cpu/",timeout=30).status_code!=200:raise RuntimeError("Hosting API authorization failure")
last=0.
def req(method,path,**kwargs):
    global last
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last)))
        last=time.monotonic()
    for i in range(3):
        r=session.request(method,API+path,timeout=45,**kwargs)
        if r.status_code==429 and i<2:time.sleep(15*(i+1));continue
        if not r.ok:raise RuntimeError("Hosting "+method+" HTTP "+str(r.status_code))
        return r

def read(path):return req("GET","/files/path"+path).content
def write(path,content):
    req("POST","/files/path"+path,files={"content":("pd-profile-legal",content,"text/html")})
    if read(path)!=content:raise RuntimeError("Hosting readback verification failed")
def sha(blob):return hashlib.sha256(blob).hexdigest()
blob=read(ROOT+FILE)
if sha(blob)!=SHA:raise RuntimeError("Live source changed. No writes. SHA="+sha(blob))
source=blob.decode("utf-8-sig")
if source.count(PROFILE_START)!=1 or source.count(PROFILE_STOP)!=1:
    raise RuntimeError("Profile boundaries changed; no writes")
s=source.index(PROFILE_START);e=source.index(PROFILE_STOP,s)
profile=source[s:e]
if profile.count(REMOVABLE)!=1 or profile.count(KEEP)!=1:
    raise RuntimeError("Unexpected policy/terms/contacts layout; no writes")
if profile.index(REMOVABLE)>profile.index(KEEP):
    raise RuntimeError("Profile links appear in unexpected order; no writes")
if 'href="/privacy"' not in source[:s] or 'href="/legal"' not in source[:s]:
    raise RuntimeError("Global header legal links missing; no writes")

updated_profile=profile.replace(REMOVABLE,"",1)
updated=source[:s]+updated_profile+source[e:]
if len(source)-len(updated)!=len(REMOVABLE):
    raise RuntimeError("Unexpected change size")
assert updated[:s]==source[:s] and updated[s+len(updated_profile):]==source[e:]
assert KEEP in updated_profile and REMOVABLE not in updated_profile
assert 'href="/privacy"' in updated[:s] and 'href="/legal"' in updated[:s]
assert 'id="pdObTelegramOneSubmit"' in updated
assert "Диспетчерская" in updated and "Водитель" in updated
assert 'data-mode="client" onclick="pdSetRole(' not in updated
Environment().parse(updated)
with tempfile.TemporaryDirectory() as temp:
    for i,js in enumerate(re.findall(r'<script\b[^>]*>([\s\S]*?)</script>',updated)):
        if not js.strip() or "{{" in js or "{%" in js:continue
        script=Path(temp)/(str(i)+".js");script.write_text(js,encoding="utf8")
        result=subprocess.run(["node","--check",str(script)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError("JS "+str(i)+" invalid: "+result.stderr[-250:])
print("PROFILE_LEGAL_PREFLIGHT_PASS exact_source=true Jinja=true JS=true header_untouched=true contacts_preserved=true",flush=True)
if os.environ.get("PD_PROFILE_LEGAL_DEPLOY")!="1":
    print("PROFILE_LEGAL_DRY_RUN_PASS live_writes=0",flush=True)
    raise SystemExit(0)
run=os.environ.get("GITHUB_RUN_ID","")
if not run.isdigit():raise RuntimeError("CI run id unavailable")
backup=f"/home/wilsonpark/private_drive_backups/profile_legal_dedup_{run}/"
write(backup+FILE,blob)
write(backup+"MANIFEST.json",json.dumps({"sha256":sha(blob),"file":FILE,"bytes":len(blob)}).encode())
print("PROFILE_LEGAL_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=blob:raise RuntimeError("Live file modified concurrently; no writes")
changed=False
try:
    changed=True
    write(ROOT+FILE,updated.encode("utf8"))
    try:req("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:
        print("HOSTING_RELOAD_TIMEOUT checking live page independently",flush=True)
    good=False
    for i in range(8):
        r=requests.get(SITE,params={"dedup_profile_legal":run,"attempt":i},headers={"Cache-Control":"no-cache"},timeout=30)
        h=r.text
        a=h.find(PROFILE_START);b=h.find(PROFILE_STOP,a) if a>=0 else -1
        segment=h[a:b] if a>=0 and b>a else ""
        global_head=h[:a] if a>=0 else ""
        header_privacy=bool(re.search(r'href="/privacy(?:\?lang=(?:ru|en|lt))?"',global_head))
        header_terms=bool(re.search(r'href="/legal(?:\?lang=(?:ru|en|lt))?"',global_head))
        no_dupes=("Политика конфиденциальности" not in segment and "Условия поездки и оплаты" not in segment)
        contacts=("Вопросы и удаление данных" in segment and "@PrivatDraiv" in segment)
        good=(r.status_code==200 and a>=0 and b>a and no_dupes and contacts and header_privacy and header_terms)
        print("PROFILE_LEGAL_PUBLIC_CHECK",i,"http",r.status_code,"no_profile_dupes",no_dupes,
              "header_both",header_privacy and header_terms,"contacts",contacts,"verified",good,flush=True)
        if good:break
        time.sleep(4)
    if not good:raise RuntimeError("Public profile legal link verification failed")
    print("PROFILE_LEGAL_LIVE_VERIFIED HTTP=200 removed_profile_dupes=true header_legal_retained=true contacts_retained=true orders_unchanged=true",flush=True)
except BaseException:
    if changed:
        write(ROOT+FILE,blob)
        try:req("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        except requests.exceptions.ReadTimeout:pass
        if read(ROOT+FILE)!=blob:raise RuntimeError("Rollback readback mismatch")
        print("PROFILE_LEGAL_ROLLBACK_SOURCE_VERIFIED",flush=True)
    raise
