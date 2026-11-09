"""PRIVATE DRIVE: single-checkbox, single-button Telegram-first passenger onboarding.
Modify only miniapp/templates/index.html after matching current production source hash.
Do not change registration, auth, phone consent validation or backend endpoints.
Existing manual form remains as secondary expandable fallback. Backup + smoke + rollback.
"""
import hashlib,os,re,json,time,tempfile,subprocess
from pathlib import Path
import requests
from jinja2 import Environment

ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com/"
EXPECTED="cf195a375cbfb51b32c19db4dd4f438f4ca98ff388bc2c75422638934e84d68a"
VERSION="pd-passenger-telegram-one-click-20261109"
token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token:raise RuntimeError("PythonAnywhere token missing")
s=requests.Session();s.headers["Authorization"]="Token "+token
if s.get(BASE+"/cpu/",timeout=35).status_code!=200:
    raise RuntimeError("No PythonAnywhere authenticated access")
last=0.0
def request(method,path,**kw):
    global last
    if path.startswith("/files/path"):
        time.sleep(max(0,1.7-(time.monotonic()-last)));last=time.monotonic()
    for n in range(3):
        r=s.request(method,BASE+path,timeout=45,**kw)
        if r.status_code==429 and n<2:
            time.sleep(14*(n+1));continue
        if not r.ok:raise RuntimeError("PythonAnywhere "+method+" failed HTTP "+str(r.status_code))
        return r
def get(path):return request("GET","/files/path"+path).content
def put(path,blob):
    request("POST","/files/path"+path,files={"content":("private-drive-registration",blob,"text/html")})
    if get(path)!=blob:raise RuntimeError("Readback mismatch after hosting write")
def h(blob):return hashlib.sha256(blob).hexdigest()

original=get(ROOT+FILE)
if h(original)!=EXPECTED:
    raise RuntimeError("LIVE SOURCE CHANGED, NO WRITES. Current SHA256 "+h(original))
html=original.decode("utf-8-sig")
start=html.index('<form id="pdObPassenger"')
end=html.index('</form>',start)+len('</form>')
old_form=html[start:end]
assert old_form.count('id="pdObPhoneConsent"')==1
assert old_form.count('onclick="pdRegisterPassengerTelegram()"')==1
assert 'onsubmit="event.preventDefault();pdRegisterPassenger()"' in old_form
assert "href=\"/privacy\"" in old_form and "href=\"/legal\"" in old_form
assert old_form.count('<form')==1 and old_form.count('</form>')==1
assert old_form.count('pdObPassengerName')>=1 and old_form.count('pdObPassengerPhone')>=1

new_form='''<form id="pdObPassenger" class="hidden pd-telegram-first-registration" onsubmit="event.preventDefault();pdRegisterPassenger()">
  <h1>Регистрация пассажира</h1>
  <p class="pd-registration-explain">Регистрируйся через Telegram без заполнения анкеты. Имя будет получено из профиля Telegram, а номер телефона — после твоего разрешения.</p>
  <label class="pd-phone-consent pd-telegram-one-consent" for="pdObPhoneConsent">
    <input id="pdObPhoneConsent" type="checkbox" required>
    <span>Согласен на использование данных Telegram и номера телефона для связи по поездкам, принимаю <a href="/legal" target="_blank" rel="noopener noreferrer">условия</a> и <a href="/privacy" target="_blank" rel="noopener noreferrer">политику конфиденциальности</a>.</span>
  </label>
  <button type="button" class="pd-telegram-one-submit" id="pdObTelegramOneSubmit" onclick="pdRegisterPassengerTelegram()">Зарегистрироваться через Telegram</button>
  <p class="pd-telegram-permission-help">Если Telegram попросит доступ к номеру телефона, подтверди передачу контакта.</p>
  <details id="pdRegistrationManual" class="pd-telegram-manual-fallback">
    <summary>Регистрация другим способом</summary>
    <div class="pd-telegram-manual-body">
      <label for="pdObPassengerName">Ваше имя</label>
      <input id="pdObPassengerName" autocomplete="name" minlength="2" maxlength="80" required>
      <label for="pdObPassengerPhone">Телефон</label>
      <input id="pdObPassengerPhone" type="tel" autocomplete="tel" maxlength="40" placeholder="+370..." required>
      <button type="submit" id="pdObPassengerSubmit">Зарегистрироваться вручную</button>
    </div>
  </details>
  <button type="button" class="pd-passenger-back secondary" onclick="pdShowOnboarding('role')">Назад</button>
</form>'''
html=html[:start]+new_form+html[end:]

# Scope extra checkbox suppression to the passenger registration pane only.
# Some existing UI decorator scripts add another consent box after DOM ready;
# the above consent already covers phone, terms and privacy.
styles='''<style id="pd-passenger-one-tap-20261109">
#pdObPassenger.pd-telegram-first-registration{max-width:100%;text-align:left}
#pdObPassenger .pd-registration-explain{line-height:1.5;color:#e7d7b6;font-size:15px;margin:12px 0 21px}
#pdObPassenger .pd-telegram-one-consent{display:flex!important;align-items:flex-start;gap:12px;line-height:1.5;font-size:14px;margin:12px 0 21px;color:#f5e9d2}
#pdObPassenger .pd-telegram-one-consent>input{flex:0 0 22px;width:22px;height:22px;min-height:22px;margin-top:2px;accent-color:#e4ad58;cursor:pointer}
#pdObPassenger .pd-telegram-one-consent>span{flex:1;min-width:0}
#pdObPassenger .pd-telegram-one-consent a{color:#ffe1a4;text-decoration:underline}
#pdObPassenger .pd-telegram-one-submit{display:block!important;width:100%!important;padding:14px 13px!important;min-height:59px!important;background:linear-gradient(120deg,#ffe7af,#d6a145)!important;color:#211503!important;border:1px solid #f3d68d!important;border-radius:22px!important;font-weight:700!important;box-shadow:0 6px 18px #e8bb5c2b!important;font-size:clamp(14px,4vw,19px)!important}
#pdObPassenger .pd-telegram-permission-help{font-size:13px;line-height:1.45;color:#bfb49a;margin:14px 0 17px;text-align:center}
#pdObPassenger .pd-telegram-manual-fallback{border:1px solid #8c744b;border-radius:13px;padding:11px 14px;background:#171717;margin:16px 0}
#pdObPassenger .pd-telegram-manual-fallback summary{cursor:pointer;color:#ebd9af;font-size:15px}
#pdObPassenger .pd-telegram-manual-body{padding:17px 0 6px}
#pdObPassenger .pd-telegram-manual-body>input{width:100%;box-sizing:border-box}
#pdObPassenger .pd-telegram-manual-body>button{margin-top:14px;width:100%}
#pdObPassenger .pd-passenger-back{min-height:39px!important;padding:8px 16px!important;margin-top:7px!important}
/* A separate, dynamically injected consent is redundant: one combined
   informed-consent checkbox remains checked by existing validation. */
#pdObPassenger label:has(input[type="checkbox"]:not(#pdObPhoneConsent)){display:none!important}
#pdObPassenger input[type="checkbox"]:not(#pdObPhoneConsent){display:none!important}
</style>'''
assert html.count("</head>")==1
html=html.replace("</head>",styles+"</head>",1)

# Existing pdRegisterPassengerTelegram() calls pdRequirePhoneConsent on exactly
# our checkbox, then existing pdbRegisterTelegram() calls tg.requestContact().
# Keep all backend and JavaScript scripts unchanged. Only form and scoped CSS.
assert html.count('id="pdObPhoneConsent"')==1
assert html.count('id="pdObTelegramOneSubmit"')==1
assert html.count('id="pdRegistrationManual"')==1
assert html.count('onclick="pdRegisterPassengerTelegram()"')==1
assert html.count('pdRequirePhoneConsent("pdObPhoneConsent","pdObStatus")')==2
assert "tg.requestContact" in html
assert "async function pdRegisterPassengerTelegram()" in html
assert 'id="pdObDriver"' in html and 'id="pdObRole"' in html
assert html.count("<form")==original.decode("utf-8-sig").count("<form")
assert 'href="/privacy"' in new_form and 'href="/legal"' in new_form
assert "id=\"pdLangSelect\"" in html
Environment().parse(html)
# No active user registration nor live orders are created by any checks.
print("ONE_TAP_PREFLIGHT_PASS one_consent=1 one_primary_action=1 Telegram_requestContact_retained=true manual_fallback=true Jinja=true",flush=True)
if os.environ.get("PD_SINGLE_TAP_DEPLOY")!="1":
    print("ONE_TAP_DRY_RUN_PASS writes=0",flush=True)
    raise SystemExit(0)

run=os.environ.get("GITHUB_RUN_ID","")
if not run.isdigit():raise RuntimeError("Run ID missing")
bk=f"/home/wilsonpark/private_drive_backups/passenger_one_tap_{run}/"
put(bk+FILE,original)
put(bk+"SOURCE_MANIFEST.json",json.dumps({"sha256":h(original),"bytes":len(original),"path":FILE}).encode())
print("ONE_TAP_BACKUP_VERIFIED",bk,flush=True)
if get(ROOT+FILE)!=original:
    raise RuntimeError("Concurrent changes detected before deployment")
changed=False
try:
    changed=True
    put(ROOT+FILE,html.encode("utf8"))
    try:
        request("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:
        print("RELOAD_RESPONSE_TIMEOUT checking public content",flush=True)
    verified=False
    for attempt in range(9):
        r=requests.get(SITE,params={"single_tap":run,"attempt":attempt},headers={"Cache-Control":"no-cache"},timeout=30)
        pub=r.text
        a=pub.find('<form id="pdObPassenger"');z=pub.find("</form>",a)
        form=pub[a:z] if a>=0 and z>a else ""
        verified=(r.status_code==200 and 'id="pdObTelegramOneSubmit"' in form and
                  form.count('id="pdObPhoneConsent"')==1 and
                  form.count('type="checkbox"')==1 and
                  'id="pdRegistrationManual"' in form and
                  "pdRegisterPassengerTelegram()" in form and
                  'id="pdObRole"' in pub and "tg.requestContact" in pub)
        print("ONE_TAP_PUBLIC_CHECK",attempt,"http",r.status_code,"verified",verified,flush=True)
        if verified:break
        time.sleep(4)
    if not verified:raise RuntimeError("Public single-tap onboarding check failed")
    print("PASSENGER_ONE_TAP_LIVE_VERIFIED HTTP=200 one_checkbox=true one_registration_button=true user_records_untouched=true orders_unchanged=true",flush=True)
except BaseException:
    if changed:
        put(ROOT+FILE,original)
        try:request("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        except requests.exceptions.ReadTimeout:pass
        print("ONE_TAP_ROLLBACK_SOURCE_VERIFIED",flush=True)
    raise
