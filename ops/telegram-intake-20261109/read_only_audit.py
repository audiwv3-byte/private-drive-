"""Read-only audit of live PRIVATE DRIVE Telegram passenger registration and dispatcher views.
Never output bot token, real contacts, user records or private databases.
"""
import os,re,requests,hashlib
session=requests.Session()
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
session.headers["Authorization"]="Token "+token
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
root="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
paths=("miniapp/templates/index.html","miniapp_server.py","Euro_Baltic_Transfer.py")
patterns={
"miniapp/templates/index.html":[
 "id=\"pdObPassenger\"","id=\"pdObPhoneConsent\"","id=\"pdObTermsConsent\"",
 "pdRequirePhoneConsent","function pdRegisterPassengerTelegram","async function pdRegisterPassengerTelegram",
 "async function pdbRegisterTelegram","function pdbRegisterTelegram","requestContact","contactRequested",
 "function pdCompletePassengerRegistration","async function pdCompletePassengerRegistration",
 "id=\"pdRegistrationManual\"","async function pdLoadAdmin","function pdLoadAdmin",
 "pdObPassengerTelegram","pdObManual","pdObPhone", "pdOnboardingStart"
],
"miniapp_server.py":[
 "def me():","def register():","def register_telegram():",
 "def admin_orders():","/api/admin/passengers","def admin_passengers",
 "def auth():","def registered_passenger", "admin","passenger_profile"
],
"Euro_Baltic_Transfer.py":[
 "def user_record(","def save_user(","def clean_phone(",
 "def register_user", "registration_phone", "content_types=['contact']", "content_types=[\"contact\"]",
 "def notify_admins(", "def phone_handler", "request_contact"
]}
for path in paths:
 r=session.get(base+"/files/path"+root+path,timeout=50)
 if not r.ok:
  print("UNAVAILABLE",path,r.status_code);continue
 s=r.content.decode("utf-8-sig")
 print("LIVE_SOURCE",path,"sha256",hashlib.sha256(r.content).hexdigest(),"bytes",len(r.content))
 for key in patterns[path]:
  positions=[m.start() for m in list(re.finditer(re.escape(key),s))[:5]]
  print("FIND",path,key,len(positions),positions)
  for i in positions[:2]:
   chunk=s[max(0,i-150):i+2200]
   # No server secrets or client records; source snippets only, output narrowly.
   if path=="Euro_Baltic_Transfer.py":chunk=s[max(0,i-130):i+1100]
   if key in ("admin","pdObPhone","pdOnboardingStart"):chunk=s[max(0,i-120):i+550]
   print("SNIP",path,key,repr(chunk))
print("READ_ONLY_AUDIT_DONE")
