"""PRIVATE DRIVE: remove only duplicated onboarding privacy link below role choices.
Keep header policy, terms, and privacy page; keep onboard contact email and Telegram.
No auth, payments, orders, databases, role buttons or language selection changes.
"""
import hashlib,json,os,re,time
from jinja2 import Environment
import requests

API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
PROJECT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
PATH="miniapp/templates/index.html"
SITE="https://wilsonpark.pythonanywhere.com/"
ANCHOR='<p id="pdObStatus" role="status"></p><p class="pdb-note">'
DUPLICATE='<a href="/privacy" target="_blank" rel="noopener noreferrer">Политика конфиденциальности</a> · '
HEADER='<div class="pd-privacy-bar"><a href="/privacy" target="_blank" rel="noopener noreferrer">Политика конфиденциальности</a>'
token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
assert token,"PythonAnywhere token unavailable"
s=requests.Session();s.headers["Authorization"]="Token "+token
assert s.get(API+"/cpu/",timeout=35).status_code==200,"PythonAnywhere credentials invalid"
last_call=0
def api(method,path,**kwargs):
    global last_call
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last_call)))
        last_call=time.monotonic()
    for i in range(3):
        r=s.request(method,API+path,timeout=40,**kwargs)
        if r.status_code==429 and i<2:
            time.sleep(15*(i+1));continue
        assert r.ok,"PythonAnywhere "+method+" HTTP "+str(r.status_code)
        return r
def get(path):return api("GET","/files/path"+path).content
def put(path,body):
    api("POST","/files/path"+path,files={"content":("private-drive-onboarding",body,"text/html")})
    assert get(path)==body,"Readback mismatch after write"
def digest(data):return hashlib.sha256(data).hexdigest()

original=get(PROJECT+PATH)
page=original.decode("utf-8-sig")
assert page.count(ANCHOR)==1,"Onboarding footer anchor changed; no writes"
assert page.count(HEADER)==1,"Header privacy policy missing; no writes"
# Remove only the lower privacy link after the role screen. Leave contact links.
start=page.index(ANCHOR)+len(ANCHOR)
end=page.index("</p>",start)
footer=page[start:end]
assert footer.startswith(DUPLICATE),"Unexpected onboarding footer structure; no writes"
assert "mailto:eurobaltictransfer@gmail.com" in footer
assert "https://t.me/PrivatDraiv" in footer
assert '<button type="button" class="secondary" onclick="pdShowOnboarding(\'language\')">Язык</button>' not in page[
    page.index('<div id="pdObRole"'):page.index('<form id="pdObPassenger"')
],"Previous duplicate language button removal not found; no writes"
updated=page[:start]+footer[len(DUPLICATE):]+page[end:]
assert len(page)-len(updated)==len(DUPLICATE),"Unrelated code changed"
assert updated[:start]==page[:start] and updated[start+len(footer)-len(DUPLICATE):]==page[end:]
assert updated.count(HEADER)==1
assert 'href="/privacy"' in updated
assert "mailto:eurobaltictransfer@gmail.com" in updated[start:start+400]
assert "https://t.me/PrivatDraiv" in updated[start:start+400]
assert 'id="pdWelcomeTelegram"' in updated and 'id="pdLangSelect"' in updated
Environment().parse(updated)
print("PRIVACY_FOOTER_PREFLIGHT_PASS source_sha256="+digest(original)[:20]+" bottom_link_removed=true header_policy_kept=true contacts_kept=true role_and_language_unchanged=true",flush=True)

if os.environ.get("PD_PRIVACY_FOOTER_DEPLOY")!="1":
    print("PRIVACY_FOOTER_DRY_RUN_PASS server_writes=0",flush=True)
    raise SystemExit(0)
run=os.environ.get("GITHUB_RUN_ID","")
assert run.isdigit(),"Missing CI run ID"
backup=f"/home/wilsonpark/private_drive_backups/duplicate_privacy_{run}/"
put(backup+PATH,original)
put(backup+"SOURCE_MANIFEST.json",json.dumps({"source":PATH,"sha256":digest(original),"size":len(original)}).encode())
print("PRIVACY_FOOTER_BACKUP_VERIFIED",backup,flush=True)
assert get(PROJECT+PATH)==original,"Concurrent production update detected, no application writes"
changed=False
try:
    changed=True
    put(PROJECT+PATH,updated.encode("utf-8"))
    api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    ok=False
    for attempt in range(8):
        r=requests.get(SITE,params={"privacy_footer_fix":run,"attempt":attempt},headers={"Cache-Control":"no-cache"},timeout=30)
        html=r.text
        a=html.find(ANCHOR)
        b=html.find("</p>",a+len(ANCHOR)) if a>=0 else -1
        lower=html[a+len(ANCHOR):b] if a>=0 and b>a else ""
        ok=(r.status_code==200 and a>=0 and DUPLICATE not in lower
            and html.count(HEADER)==1
            and "mailto:eurobaltictransfer@gmail.com" in lower
            and "https://t.me/PrivatDraiv" in lower
            and 'id="pdLangSelect"' in html and 'id="pdWelcomeTelegram"' in html)
        print("PRIVACY_FOOTER_PUBLIC_CHECK",attempt,"HTTP",r.status_code,"verified",ok,flush=True)
        if ok:break
        time.sleep(4)
    if not ok:raise RuntimeError("Public privacy footer verification failed")
    print("PRIVACY_FOOTER_LIVE_VERIFIED HTTP=200 duplicate_removed=true top_link_kept=true contacts_kept=true db_writes=0",flush=True)
except BaseException:
    if changed:
        put(PROJECT+PATH,original)
        api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        print("PRIVACY_FOOTER_ROLLBACK_VERIFIED",flush=True)
    raise
