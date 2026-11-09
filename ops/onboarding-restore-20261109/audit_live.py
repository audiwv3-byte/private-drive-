"""Read-only production onboarding audit. Never prints source, tokens or customer data."""
import hashlib, os, re, sys
import requests
TOKEN = re.sub(r"^Token\\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I)
TOKEN = "".join(TOKEN.split())
if not TOKEN: raise RuntimeError("PA_API_TOKEN not configured")
base = "https://www.pythonanywhere.com/api/v0/user/wilsonpark"
site = "https://wilsonpark.pythonanywhere.com"
project = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
s = requests.Session()
s.headers["Authorization"] = "Token " + TOKEN
probe = s.get(base + "/cpu/", timeout=30)
assert probe.status_code == 200, "Hosting API credentials error HTTP " + str(probe.status_code)
def read(name):
    r=s.get(base + "/files/path" + project + name, timeout=40)
    if r.status_code==404:return None
    assert r.status_code==200, "Read of "+name+" blocked: HTTP "+str(r.status_code)
    return r.content
for f in ["miniapp/templates/index.html", "pd_registration.js", "pd_tips_widget.py"]:
    data=read(f)
    if data is None:
        print("REMOTE_FILE",f,"NOT_FOUND")
        continue
    text=data.decode("utf-8-sig",errors="replace")
    flags={}
    if f.endswith("index.html"):
        flags={
            "has_language_panel":'id="pdObLanguage"' in text,
            "has_telegram_button":"pdRegisterPassengerTelegram()" in text,
            "flags_en_lt_ru":all(x in text for x in ("🇬🇧","🇱🇹","🇷🇺")),
            "has_registration_js_link":"pd-registration.js" in text,
            "has_first_visitor_language":"if(!chosen){pdShowOnboarding('language');return}" in text,
            "has_logo_link":"private-drive-official-logo.jpeg" in text,
            "has_manual_passenger_fields":'id="pdObPassengerName"' in text,
        }
    if f.endswith("pd_registration.js"):
        flags={
            "suppresses_language": "guest&&(stage==='role'||stage==='language')?'passenger':stage" in text,
            "sets_direct_passenger_on_load": "pdShowOnboarding('passenger')" in text,
            "replaces_logo": "private-drive-logo-transparent-v1.png" in text,
            "consent_check": "pdRegistrationConsent" in text,
        }
    print("REMOTE_FILE",f,"bytes",len(data),"sha256",hashlib.sha256(data).hexdigest()[:20],"markers",flags)
for url in [site + "/",site + "/assets/pd-registration.js",site + "/assets/private-drive-official-logo.jpeg"]:
    try:
        r=requests.get(url,timeout=25)
        print("PUBLIC_URL",url.replace(site,""),"HTTP",r.status_code,"bytes",len(r.content),"sha256",hashlib.sha256(r.content).hexdigest()[:20],"has_flags",all(x in r.text for x in ('🇬🇧','🇱🇹','🇷🇺')) if r.status_code==200 else False,"visible_code_matches",("pdShowOnboarding('passenger')" in r.text) if url.endswith(".js") and r.status_code==200 else "n/a")
    except requests.RequestException:
        print("PUBLIC_URL",url.replace(site,""),"NOT_RESPONDING")
print("READ_ONLY_AUDIT_DONE no_hosting_writes=true")

# Check only the error TYPE and module, never emit request details or full tracebacks.
r=s.get(base+"/files/path/var/log/wilsonpark.pythonanywhere.com.error.log",timeout=30)
print("ERROR_LOG_READ_STATUS",r.status_code)
if r.status_code==200:
    frame=[]
    for line in r.text.splitlines()[-500:]:
        m=re.search(r'File "([^"]+)", line ([0-9]+)',line)
        if m:frame.append((m.group(1).split("/")[-1],m.group(2)))
        er=re.search(r'([A-Za-z.]*?(?:SyntaxError|TemplateSyntaxError|AttributeError|NameError|TypeError|ImportError|RuntimeError|UndefinedError))\\b',line)
        if er:
            print("ERROR_EXCEPTION",er.group(1),"RECENT_FRAMES",frame[-3:])
            frame.clear()
import subprocess
check=subprocess.run([sys.executable,"ops/onboarding-restore-20261109/deploy_ui.py"],
    env={**os.environ,"PD_UI_DEPLOY":"0"},text=True,capture_output=True)
print("DRY_RUN_SOURCE_CHECK_EXIT",check.returncode)
for line in check.stdout.splitlines():
    if line.startswith(("LIVE_SOURCE_FINGERPRINTS","OFFLINE_SYNTAX","PATCH_PREFLIGHT","DRY_RUN")):print(line)
if check.returncode:
    for line in check.stderr.splitlines()[-6:]: print("DRY_RUN_ERROR_TYPE",line[:160])

# Geo prompt root-cause audit: print only bounded public-source context, not private data.
source=read("miniapp/templates/index.html")
if source:
    html=source.decode("utf-8-sig",errors="replace")
    print("GEO_AUDIT_TEMPLATE_BYTES",len(html))
    for needle in ("Показать вас на карте","Определим ваше местоположение","Адрес можно указать вручную","Запрашивается только с вашего разрешения","geolocation.getCurrentPosition","getCurrentPosition(","watchPosition(","pdOnboardingStage","pdObLanguage","pdShowGeo","geoConsent"):
        matches=list(re.finditer(re.escape(needle),html,re.I))
        print("GEO_MATCH",repr(needle),"count",len(matches))
        for m in matches[:4]:
            left=max(0,m.start()-450);right=min(len(html),m.end()+720)
            print("GEO_CONTEXT",repr(needle),"index",m.start(),repr(html[left:right]))
    print("GEO_SCRIPT_URLS",re.findall(r'<script[^>]+src="([^"]+)"',html)[-25:])
