"""Release approved PRIVATE DRIVE first screen from existing official branding and night photo.
Exactly one application template changes. No registration API, orders, DB, payment or GPS writes.
Live hash precondition, private verified backup, Jinja/JS tests, public smoke check, auto-rollback.
"""
import hashlib, json, os, re, subprocess, tempfile, time
import requests
from jinja2 import Environment

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
SITE="https://wilsonpark.pythonanywhere.com/"
OLD_SHA="1db4da9622b46364c5e228530ae34dd0a592c1f8da8edb3f25a0ea49ed79c94d"
VERSION="welcome-approved-20261109-v1"
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I)
token="".join(token.split())
if not token: raise RuntimeError("Missing PythonAnywhere API token")
session=requests.Session()
session.headers["Authorization"]="Token "+token
if session.get(BASE+"/cpu/",timeout=30).status_code != 200:
    raise RuntimeError("PythonAnywhere API access failed")
last_request=0
def api(method,path,**kwargs):
    global last_request
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last_request)))
        last_request=time.monotonic()
    for retry in range(3):
        r=session.request(method,BASE+path,timeout=40,**kwargs)
        if r.status_code==429 and retry<2:
            time.sleep(15*(retry+1));continue
        if not r.ok: raise RuntimeError("PythonAnywhere API "+method+" HTTP "+str(r.status_code))
        return r
def read(path):
    return api("GET","/files/path"+path).content
def write(path,content):
    api("POST","/files/path"+path,files={"content":("private-drive-welcome",content,"text/plain")})
    if read(path)!=content: raise RuntimeError("Write verification failed")
def sha(content):return hashlib.sha256(content).hexdigest()

source=read(ROOT+FILE)
if sha(source)!=OLD_SHA:
    raise RuntimeError("Live template changed; refusing to overwrite unknown edits. Current hash: "+sha(source)[:20])
html=source.decode("utf-8-sig")
start=html.index('<div id="pdObLanguage"')
end=html.index('<div id="pdObRole"',start)
old=html[start:end]
assert len(old)<1900 and old.count("pdChooseInitialLanguage") == 3 and "private-drive-official-logo.jpeg" in old
if VERSION in html:raise RuntimeError("Approved welcome already present")

welcome="""<div id="pdObLanguage" class="hidden" aria-label="PRIVATE DRIVE — выбор языка">
<div class="pd-welcome-head">
  <img class="pd-ob-hero-logo" src="/assets/private-drive-official-logo.jpeg" alt="Фирменный логотип PD — PRIVATE DRIVE" width="220" height="220" fetchpriority="high">
  <p class="pd-welcome-tagline" id="pdWelcomeTagline">Комфортные поездки по Литве и Европе</p>
  <h1 id="pdWelcomeTitle">Выберите язык</h1>
</div>
<div class="pd-ob-language-options pd-welcome-choices" role="group" aria-label="Language / Kalba / Язык">
  <button type="button" lang="en" aria-pressed="false" onclick="pdWelcomeSelect('en')"><span class="pd-ob-flag" aria-hidden="true">🇬🇧</span><span>English</span></button>
  <button type="button" lang="lt" aria-pressed="false" onclick="pdWelcomeSelect('lt')"><span class="pd-ob-flag" aria-hidden="true">🇱🇹</span><span>Lietuvių</span></button>
  <button type="button" lang="ru" aria-pressed="true" onclick="pdWelcomeSelect('ru')"><span class="pd-ob-flag" aria-hidden="true">🇷🇺</span><span>Русский</span></button>
</div>
<div class="pd-welcome-car" role="img" aria-label="Автомобиль PRIVATE DRIVE на фоне ночного города"></div>
<button type="button" class="pd-welcome-telegram" id="pdWelcomeTelegram" onclick="pdWelcomeContinue(false)"><span class="pd-welcome-telegram-icon" aria-hidden="true">✈</span><span id="pdWelcomeTelegramText">Продолжить с Telegram</span></button>
<button type="button" class="pd-welcome-manual" id="pdWelcomeManual" onclick="pdWelcomeContinue(true)">Регистрация другим способом</button>
</div>
"""
html=html[:start]+welcome+html[end:]
style="""<style id="pd-welcome-approved-20261109">
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) .pd-branded-header,
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) .pd-privacy-bar,
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) footer,
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) #pdTipsAlways{display:none!important}
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)){background:#020304!important}
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) .shell{max-width:640px!important;padding:0 0 24px!important}
body.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) #pdOnboarding{background:transparent!important;box-shadow:none!important;border:0!important;padding:0!important;margin:0 auto!important;max-width:640px!important}
#pdObLanguage:not(.hidden){display:flex!important;flex-direction:column;align-items:center;background:#020304!important;border:0!important;border-radius:0!important;max-width:100%!important;margin:0!important;padding:12px 18px 30px!important;color:#f3e3be!important;text-align:center}
#pdObLanguage .pd-welcome-head{width:100%;display:flex;flex-direction:column;align-items:center;gap:6px}
#pdObLanguage .pd-ob-hero-logo{width:clamp(160px,48vw,242px)!important;height:auto!important;aspect-ratio:1!important;object-fit:contain!important;margin:0 auto 8px!important;filter:drop-shadow(0 4px 14px #e7aa5730)}
#pdObLanguage .pd-welcome-tagline{margin:0 0 5px!important;color:#f7eee1;font-size:clamp(12px,3.4vw,17px);line-height:1.4;letter-spacing:.2px}
#pdObLanguage #pdWelcomeTitle{font:700 clamp(24px,6vw,34px)/1.2 Arial,sans-serif!important;margin:3px 0 14px!important;color:#fff!important}
#pdObLanguage .pd-welcome-choices{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));width:100%;gap:8px;margin:0 auto 8px!important}
#pdObLanguage .pd-welcome-choices button{display:flex!important;flex-direction:row!important;justify-content:center!important;align-items:center!important;gap:6px!important;min-height:57px!important;padding:8px 5px!important;font:600 clamp(11px,3vw,16px)/1.2 Arial,sans-serif!important;white-space:nowrap!important;color:#f5ebdf!important;background:linear-gradient(140deg,#171719,#050608)!important;border:1.5px solid #d4a64c!important;border-radius:16px!important;box-shadow:none!important;transform:none!important}
#pdObLanguage .pd-welcome-choices button[aria-pressed="true"]{background:linear-gradient(140deg,#ffe1a1,#c58829)!important;color:#160e03!important;box-shadow:0 0 15px #e5ad4f65!important}
#pdObLanguage .pd-welcome-choices .pd-ob-flag{font-size:clamp(20px,6vw,31px)!important;line-height:1!important}
#pdObLanguage .pd-welcome-car{width:calc(100% + 36px);height:clamp(185px,53vw,300px);background-image:linear-gradient(to bottom,#020304 0%,transparent 14%,transparent 78%,#020304 100%),url("/assets/private-drive-night.png");background-position:center,center;background-size:cover,cover;background-repeat:no-repeat;margin:0 -18px 5px!important}
#pdObLanguage .pd-welcome-telegram{display:flex!important;align-items:center;justify-content:center;gap:14px;width:100%;min-height:62px;padding:12px 16px;margin:0!important;border:1.5px solid #f7db98!important;border-radius:40px!important;background:linear-gradient(120deg,#ffe9b3,#d5a34b)!important;color:#130e05!important;font:700 clamp(15px,4.2vw,22px)/1.2 Arial,sans-serif!important;box-shadow:0 5px 15px #d3a45624!important}
#pdObLanguage .pd-welcome-telegram-icon{display:inline-grid;place-items:center;width:36px;height:36px;background:#22abe0;color:#fff;border-radius:50%;font-size:22px;flex-shrink:0}
#pdObLanguage .pd-welcome-manual{background:transparent!important;border:0!important;color:#f5f5f5!important;font:500 clamp(14px,4vw,18px)/1.4 Arial,sans-serif!important;text-decoration:underline!important;text-underline-offset:4px!important;margin:14px 0 0!important;padding:5px!important;box-shadow:none!important}
@media(max-width:380px){ #pdObLanguage:not(.hidden){padding:10px 12px 24px!important}#pdObLanguage .pd-welcome-choices{gap:5px}#pdObLanguage .pd-welcome-choices button{padding:5px 2px!important;border-radius:12px!important}#pdObLanguage .pd-welcome-car{width:calc(100% + 24px);margin:0 -12px 5px!important} }
</style>"""
assert html.count("</head>")==1
html=html.replace("</head>",style+"</head>",1)
script="""<script id="pd-welcome-ui-20261109">
(function(){
 const copy={
 ru:{tag:'Комфортные поездки по Литве и Европе',title:'Выберите язык',telegram:'Продолжить с Telegram',manual:'Регистрация другим способом'},
 en:{tag:'Comfortable rides across Lithuania and Europe',title:'Choose language',telegram:'Continue with Telegram',manual:'Register another way'},
 lt:{tag:'Patogios kelionės Lietuvoje ir Europoje',title:'Pasirinkite kalbą',telegram:'Tęsti su Telegram',manual:'Registruotis kitu būdu'}
 };
 let selected=['ru','en','lt'].includes(window.PD_LANG)?window.PD_LANG:'ru';
 window.pdWelcomeSelect=function(lang){
   if(!copy[lang])return;
   selected=lang;
   for(const b of document.querySelectorAll('#pdObLanguage .pd-welcome-choices button')){
     b.setAttribute('aria-pressed',String(b.lang===lang));
   }
   const t=copy[lang];
   document.getElementById('pdWelcomeTagline').textContent=t.tag;
   document.getElementById('pdWelcomeTitle').textContent=t.title;
   document.getElementById('pdWelcomeTelegramText').textContent=t.telegram;
   document.getElementById('pdWelcomeManual').textContent=t.manual;
 };
 window.pdWelcomeContinue=function(manual){
   try{localStorage.setItem('pdOnboardingLanguage',selected)}catch(_){}
   pdObStore('pdOnboardingStage','passenger');
   if(manual)pdObStore('pdWelcomeManualPending','yes');
   if(selected!==window.PD_LANG){pdSwitchLanguage(selected);return}
   pdShowOnboarding('passenger');
   if(manual){
      const d=document.getElementById('pdRegistrationManual');
      if(d)d.open=true;
   }
 };
 window.addEventListener('load',function(){
   window.pdWelcomeSelect(selected);
   if(pdObRead('pdWelcomeManualPending')==='yes'){
     pdObStore('pdWelcomeManualPending',null);
     const d=document.getElementById('pdRegistrationManual');
     if(d)d.open=true;
   }
 });
})();
</script>"""
assert html.count("</body>")==1
html=html.replace("</body>",script+"</body>",1)
# Ensure original accounts/permissions are unaffected and static asset exists on live domain.
assert all(s in html for s in ["pdWelcomeSelect","pdWelcomeContinue","/assets/private-drive-night.png","private-drive-official-logo.jpeg"])
assert html.count('id="pdObLanguage"')==1 and html.count('id="pdWelcomeTelegram"')==1
assert 'pdRegisterPassengerTelegram()' in html
Environment().parse(html)
with tempfile.NamedTemporaryFile("w",encoding="utf8",suffix=".js") as tmp:
    tmp.write(script[script.index("(function()"):script.rindex("</script>")]);tmp.flush()
    check=subprocess.run(["node","--check",tmp.name],capture_output=True,text=True)
    if check.returncode:raise RuntimeError("Welcome JavaScript syntax failure")
print("APPROVED_WELCOME_PREFLIGHT_PASS template=true javascript=true original_logo=true existing_registration=true",flush=True)
if os.environ.get("PD_WELCOME_DEPLOY")!="1":
    print("APPROVED_WELCOME_DRY_RUN_PASS hosting_writes=0",flush=True)
    raise SystemExit(0)
run=os.environ.get("GITHUB_RUN_ID","")
assert run.isdigit()
backup=f"/home/wilsonpark/private_drive_backups/welcome_approved_{run}/"
write(backup+FILE,source)
write(backup+"MANIFEST.json",json.dumps({"sha256":sha(source),"bytes":len(source),"source":FILE}).encode())
print("APPROVED_WELCOME_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=source:raise RuntimeError("Live file changed concurrently: no application writes")
changed=False
try:
    changed=True
    write(ROOT+FILE,html.encode("utf-8"))
    api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    public=requests.Session()
    ok=False
    for attempt in range(8):
        r=public.get(SITE,params={"welcome_revision":VERSION,"retry":str(attempt)},timeout=30,headers={"Cache-Control":"no-cache"})
        ok=(r.status_code==200 and 'id="pdWelcomeTelegram"' in r.text
          and "private-drive-official-logo.jpeg" in r.text
          and "pdWelcomeSelect" in r.text and "/assets/private-drive-night.png" in r.text)
        print("APPROVED_WELCOME_PUBLIC_CHECK",attempt,"http",r.status_code,"features_present",ok,flush=True)
        if ok:break
        time.sleep(4)
    if not ok:raise RuntimeError("Public page smoke check failed")
    print("APPROVED_WELCOME_LIVE_VERIFIED","HTTP=200","db_writes=0","payments_unchanged=true",flush=True)
except BaseException:
    if changed:
        write(ROOT+FILE,source)
        api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        print("APPROVED_WELCOME_ROLLBACK_VERIFIED",flush=True)
    raise
