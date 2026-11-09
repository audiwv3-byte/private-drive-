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
        print("PUBLIC_URL",url.replace(site,""),"HTTP",r.status_code,"bytes",len(r.content),"visible_code_matches",("pdShowOnboarding('passenger')" in r.text) if url.endswith(".js") and r.status_code==200 else "n/a")
    except requests.RequestException:
        print("PUBLIC_URL",url.replace(site,""),"NOT_RESPONDING")
print("READ_ONLY_AUDIT_DONE no_hosting_writes=true")
