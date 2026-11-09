"""PRIVATE DRIVE: remove duplicate support and legal links inside passenger profile.
The global header legal links, shared contact footer, phone consent, personal
data, orders and payment behavior stay intact. Guarded one-template deployment.
"""
import hashlib,os,re,time,json,subprocess,tempfile
from pathlib import Path
import requests
from jinja2 import Environment

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
SITE="https://wilsonpark.pythonanywhere.com/"
EXPECTED="d665a56ff15b0aadf9fd40fd63e455829ee50dc4546b6337441d3355eadb4a14"

TOP_START='<section class="panel hidden" id="step14"><h1>Мой профиль</h1>'
TOP_LINKS='<p class="pdb-note"><a href="mailto:eurobaltictransfer@gmail.com">Вопросы и удаление данных</a> · <a href="https://t.me/PrivatDraiv" target="_blank" rel="noopener noreferrer" data-pd-telegram-contact="true">@PrivatDraiv</a></p>'
PROFILE_START='<div class="pdb-price" id="pdbProfile">'
PROFILE_END='<button type="button" id="pdbTelegramRegister"'
NOTICE_START='<p class="pdb-note pd-privacy-notice">'
NOTICE_SUMMARY='Имя, телефон и сведения о поездке используются для регистрации и выполнения заказа. Email, город и постоянные пожелания необязательны.'
NOTICE_LINKS=' <a href="/privacy" target="_blank" rel="noopener noreferrer">Политика конфиденциальности</a> · <a href="/legal" target="_blank" rel="noopener noreferrer">Условия поездки и оплаты</a>. Обращения о данных: <a href="mailto:eurobaltictransfer@gmail.com">eurobaltictransfer@gmail.com</a> · <a href="https://t.me/PrivatDraiv" target="_blank" rel="noopener noreferrer" data-pd-telegram-contact="true">@PrivatDraiv</a>.'
FULL_NOTICE=NOTICE_START+NOTICE_SUMMARY+NOTICE_LINKS+'</p>'
SHORT_NOTICE=NOTICE_START+NOTICE_SUMMARY+'</p>'

token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token:raise RuntimeError("PythonAnywhere credentials not available")
ses=requests.Session();ses.headers={"Authorization":"Token "+token}
if ses.get(BASE+"/cpu/",timeout=35).status_code!=200:raise RuntimeError("PythonAnywhere authentication unavailable")
last_request=0.
def api(method,path,**kwargs):
    global last_request
    if path.startswith("/files/path"):
        time.sleep(max(0,1.7-(time.monotonic()-last_request)))
        last_request=time.monotonic()
    for attempt in range(3):
        res=ses.request(method,BASE+path,timeout=45,**kwargs)
        if res.status_code==429 and attempt<2:
            time.sleep(15*(attempt+1));continue
        if not res.ok:raise RuntimeError("Hosting API HTTP "+str(res.status_code)+" for "+method)
        return res
def read(path):return api("GET","/files/path"+path).content
def write(path,data):
    api("POST","/files/path"+path,files={"content":("private-drive-profile",data,"text/html")})
    if read(path)!=data:raise RuntimeError("Hosting readback mismatch")
def sha(blob):return hashlib.sha256(blob).hexdigest()

original=read(ROOT+FILE)
if sha(original)!=EXPECTED:
    raise RuntimeError("Concurrent live change detected. No writes. SHA "+sha(original))
source=original.decode("utf-8-sig")
top=source.find(TOP_START)
card=source.find(PROFILE_START)
if top<0 or card<0:raise RuntimeError("Passenger profile boundaries changed")
stop=source.find(PROFILE_END,card)
top_end=source.find('<div id="pdProfilePageHome">',top)
if stop<0 or top_end<0:raise RuntimeError("Profile substructure changed")
head=source[top:top_end]
body=source[card:stop]
if head.count(TOP_LINKS)!=1 or body.count(FULL_NOTICE)!=1:
    raise RuntimeError("Duplicate profile text differs; no writes")
if source.count(TOP_LINKS)!=1:
    raise RuntimeError("Unexpected repeated top support note")
if source.count(FULL_NOTICE)!=2:
    raise RuntimeError("Unexpected duplicate notice structure")
if 'class="pd-privacy-bar"' not in source or 'class="pd-contact-footer' not in source:
    raise RuntimeError("Global header or footer missing; no writes")
if not all(x in source[:card] for x in ('href="/privacy"','href="/legal"')):
    raise RuntimeError("Top legal links absent; no writes")
updated=source[:card]+body.replace(FULL_NOTICE,SHORT_NOTICE,1)+source[stop:]
updated=updated.replace(TOP_LINKS,"",1)
assert len(source)-len(updated)==len(TOP_LINKS)+len(FULL_NOTICE)-len(SHORT_NOTICE)
assert updated.count(TOP_LINKS)==0
assert updated.count(FULL_NOTICE)==1
assert updated.count(SHORT_NOTICE)==1
assert '<section class="panel hidden" id="step14"><h1>Мой профиль</h1><p>Ваши контакты' in updated
new_card=updated[updated.index(PROFILE_START):updated.index(PROFILE_END,updated.index(PROFILE_START))]
assert 'href="/privacy"' not in new_card and 'href="/legal"' not in new_card
assert 'mailto:eurobaltictransfer@gmail.com' not in new_card
assert 'https://t.me/PrivatDraiv' not in new_card
assert 'id="pdbPhoneConsent"' in new_card
assert 'id="pdbProfileSummary"' in new_card
assert 'class="pd-contact-footer' in updated
assert 'class="pd-privacy-bar"' in updated
assert updated.count('id="pdObTelegramOneSubmit"')==source.count('id="pdObTelegramOneSubmit"')
assert 'id="pdCustomers"' in updated and 'id="pdbOrigin"' in updated
Environment().parse(updated)

with tempfile.TemporaryDirectory() as td:
    checked=0
    for i,js in enumerate(re.findall(r'<script\b[^>]*>([\s\S]*?)</script>',updated)):
        if not js.strip() or '{{' in js or '{%' in js:continue
        p=Path(td)/(str(i)+".js");p.write_text(js,encoding="utf8")
        check=subprocess.run(["node","--check",str(p)],capture_output=True,text=True)
        if check.returncode:raise RuntimeError("JS script "+str(i)+" invalid: "+check.stderr[-350:])
        checked+=1
print("PROFILE_CONTACTS_PREFLIGHT_PASS profile_only=true header_kept=true footer_kept=true consent_kept=true jinja=true js="+str(checked),flush=True)
if os.environ.get("PD_PROFILE_LINKS_DEPLOY")!="1":
    print("PROFILE_CONTACTS_DRY_RUN_PASS server_writes=0",flush=True)
    raise SystemExit(0)

run=os.environ.get("GITHUB_RUN_ID","")
if not run.isdigit():raise RuntimeError("CI run ID missing")
backup=f"/home/wilsonpark/private_drive_backups/profile_contacts_dedup_{run}/"
write(backup+FILE,original)
write(backup+"MANIFEST.json",json.dumps({"sha256":sha(original),"path":FILE,"bytes":len(original)}).encode())
print("PROFILE_CONTACTS_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=original:raise RuntimeError("Concurrent live file modification; deployment blocked")
changed=False
try:
    changed=True
    write(ROOT+FILE,updated.encode("utf8"))
    try:api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:
        print("HOSTING_RELOAD_READ_TIMEOUT will independently verify public result",flush=True)
    success=False
    for i in range(8):
        res=requests.get(SITE,params={"profile_contact_dedup":run,"attempt":i},
                         headers={"Cache-Control":"no-cache"},timeout=30)
        html=res.text
        a=html.find(TOP_START);e=html.find('<div id="pdProfilePageHome">',a) if a>=0 else -1
        c=html.find(PROFILE_START);d=html.find(PROFILE_END,c) if c>=0 else -1
        head=html[a:e] if e>a>=0 else ""
        card=html[c:d] if d>c>=0 else ""
        has_head_legal=bool(re.search(r'href="/privacy(?:\?lang=(?:ru|en|lt))?"',html[:a])) and bool(re.search(r'href="/legal(?:\?lang=(?:ru|en|lt))?"',html[:a]))
        no_top_dup="Вопросы и удаление данных" not in head and "@PrivatDraiv" not in head
        no_card_dup=(bool(card) and "Политика конфиденциальности" not in card and
            "Условия поездки и оплаты" not in card and "eurobaltictransfer@gmail.com" not in card and
            "@PrivatDraiv" not in card)
        retained=all(x in html for x in ('class="pd-contact-footer','id="pdbPhoneConsent"','id="pdbProfileSummary"'))
        success=res.status_code==200 and has_head_legal and no_top_dup and no_card_dup and retained
        print("PROFILE_CONTACTS_PUBLIC_CHECK",i,"http",res.status_code,
              "no_top_links",no_top_dup,"no_card_links",no_card_dup,
              "global_links",has_head_legal,"verified",success,flush=True)
        if success:break
        time.sleep(4)
    if not success:raise RuntimeError("Public profile dedup verification failed")
    print("PROFILE_CONTACTS_LIVE_VERIFIED HTTP=200 duplicates_removed=true global_links_kept=true orders_untouched=true",flush=True)
except BaseException:
    if changed:
        write(ROOT+FILE,original)
        try:api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        except requests.exceptions.ReadTimeout:pass
        if read(ROOT+FILE)!=original:raise RuntimeError("Rollback readback failed")
        print("PROFILE_CONTACTS_ROLLBACK_VERIFIED",flush=True)
    raise
