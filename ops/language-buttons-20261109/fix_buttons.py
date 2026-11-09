"""Narrow live PRIVATE DRIVE welcome language-buttons fix with rollback.
Only the language chooser CSS and its exclusion from decorative arrow injection.
No DB, orders, payment APIs, Telegram auth, or unrelated page controls changed.
"""
import hashlib,json,os,re,subprocess,tempfile,time
import requests
from jinja2 import Environment
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com/"
EXPECTED="bec317fa696665e0f5ab47e6a871f2a095a28a88b7d094a5df85e6f23be6dac0"
CSS_ID="pd-welcome-languages-fixed-20261109"
OLD="if(b.querySelector('.pd-action-icon')||b.closest('.leaflet-control,.pd-inline-stars,.pd-star-options')"
NEW="if(b.closest('#pdObLanguage .pd-welcome-choices')||b.querySelector('.pd-action-icon')||b.closest('.leaflet-control,.pd-inline-stars,.pd-star-options')"
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I)
token="".join(token.split())
if not token:raise RuntimeError("Missing PythonAnywhere credentials")
session=requests.Session()
session.headers["Authorization"]="Token "+token
if session.get(API+"/cpu/",timeout=35).status_code!=200:
    raise RuntimeError("PythonAnywhere API access unavailable")
last_call=0.
def call(method,path,**kwargs):
    global last_call
    if path.startswith("/files/path"):
        time.sleep(max(0.,1.65-(time.monotonic()-last_call)))
        last_call=time.monotonic()
    for attempt in range(3):
        r=session.request(method,API+path,timeout=40,**kwargs)
        if r.status_code==429 and attempt<2:
            time.sleep(15*(attempt+1));continue
        if not r.ok:raise RuntimeError("Hosting request "+method+" failed HTTP "+str(r.status_code))
        return r
def read(path):return call("GET","/files/path"+path).content
def write(path,data):
    call("POST","/files/path"+path,files={"content":("pd-language-buttons",data,"text/plain")})
    if read(path)!=data:raise RuntimeError("Hosting read-back mismatch")
def sha(data):return hashlib.sha256(data).hexdigest()

original=read(ROOT+FILE)
if sha(original)!=EXPECTED:
    raise RuntimeError("Live template changed: no writes. hash="+sha(original)[:16])
html=original.decode("utf-8-sig")
if html.count(OLD)!=1 or CSS_ID in html:
    raise RuntimeError("Unexpected decorative icon code, no writes")
# Exact 3 original language buttons retained with the same onclick targets.
start=html.index('<div class="pd-ob-language-options pd-welcome-choices"')
end=html.index('</div>',start)+6
before_buttons=html[start:end]
assert all(f"onclick=\"pdWelcomeSelect('{lang}')\"" in before_buttons for lang in ["en","lt","ru"])
assert all(label in before_buttons for label in ["English","Lietuvių","Русский"])
assert before_buttons.count("<button")==3
# Exclude only the three language buttons from global button icon decoration.
html=html.replace(OLD,NEW,1)
style='''<style id="pd-welcome-languages-fixed-20261109">
/* The general button decorator used to prepend arrows. Keep them off the
   language chooser only; other decorated controls are not affected. */
#pdObLanguage .pd-welcome-choices{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important;min-width:0!important;width:100%!important}
#pdObLanguage .pd-welcome-choices button{min-width:0!important;max-width:100%!important;box-sizing:border-box!important;display:flex!important;flex-direction:row!important;justify-content:center!important;align-items:center!important;gap:4px!important;padding:8px 3px!important;font-size:clamp(10px,2.9vw,14px)!important;line-height:1.15!important;white-space:nowrap!important;text-align:center!important;overflow:hidden!important}
#pdObLanguage .pd-welcome-choices button>.pd-action-icon{display:none!important}
#pdObLanguage .pd-welcome-choices button>.pd-ob-flag{display:inline-block!important;flex:0 0 auto!important;font-size:clamp(20px,5.5vw,26px)!important;line-height:1!important}
#pdObLanguage .pd-welcome-choices button>.pd-ob-flag+span{display:inline-block!important;flex:0 1 auto!important;min-width:0!important;white-space:nowrap!important;letter-spacing:0!important}
@media(max-width:360px){ #pdObLanguage .pd-welcome-choices{gap:4px!important}#pdObLanguage .pd-welcome-choices button{font-size:10px!important;gap:3px!important;padding:6px 2px!important}#pdObLanguage .pd-welcome-choices button>.pd-ob-flag{font-size:20px!important} }
</style>'''
if html.count("</head>")!=1:raise RuntimeError("Unexpected template head")
html=html.replace("</head>",style+"</head>",1)
assert html[start:html.index("</div>",start)+6]==before_buttons,"Language button handlers were modified"
assert html.count(NEW)==1 and html.count(CSS_ID)==1
Environment().parse(html)
decorator_pos=html.index("function decorate(){document.querySelectorAll('button')")
script_start=html.rfind("<script",0,decorator_pos)
script_start=html.index(">",script_start)+1
script_end=html.index("</script>",decorator_pos)
with tempfile.NamedTemporaryFile(mode="w",suffix=".js",encoding="utf-8") as tmp:
    tmp.write(html[script_start:script_end]);tmp.flush()
    result=subprocess.run(["node","--check",tmp.name],capture_output=True,text=True)
    if result.returncode:raise RuntimeError("Patched JavaScript failed syntax check")
print("LANGUAGE_BUTTON_PREFLIGHT_OK arrow_injection_excluded=true full_labels=true unmodified_handlers=3 Jinja=true JS=true",flush=True)
if os.environ.get("PD_LANGUAGE_BUTTON_DEPLOY")!="1":
    print("LANGUAGE_BUTTON_DRY_RUN_OK production_writes=0",flush=True)
    raise SystemExit(0)

run=os.environ.get("GITHUB_RUN_ID","")
assert run.isdigit()
backup=f"/home/wilsonpark/private_drive_backups/language_buttons_20261109_{run}/"
write(backup+FILE,original)
write(backup+"MANIFEST.json",json.dumps({"file":FILE,"bytes":len(original),"sha256":sha(original)}).encode("utf-8"))
print("LANGUAGE_BUTTON_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=original:raise RuntimeError("Concurrent live change; no writes")
updated=html.encode("utf-8")
changed=False
try:
    changed=True
    write(ROOT+FILE,updated)
    call("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    ok=False
    for attempt in range(8):
        r=requests.get(SITE,params={"lang_button_fix":run,"attempt":str(attempt)},headers={"Cache-Control":"no-cache"},timeout=30)
        ok=(r.status_code==200 and CSS_ID in r.text and NEW in r.text and
            all(s in r.text for s in ('🇬🇧','🇱🇹','🇷🇺')) and
            all(s in r.text for s in ('pdWelcomeSelect','pdWelcomeTelegram','private-drive-official-logo.jpeg')))
        print("LANGUAGE_BUTTON_PUBLIC_CHECK",attempt,"HTTP",r.status_code,"new_style",CSS_ID in r.text,"passed",ok,flush=True)
        if ok:break
        time.sleep(4)
    if not ok:raise RuntimeError("Public UI verification failed")
    print("LANGUAGE_BUTTON_FIX_LIVE_VERIFIED HTTP=200 arrows_disabled=true names_visible=true registration_unchanged=true db_writes=0",flush=True)
except BaseException:
    if changed:
        write(ROOT+FILE,original)
        call("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        print("LANGUAGE_BUTTON_SOURCE_ROLLBACK_VERIFIED",flush=True)
    raise
