"""Read-only PR29 web route compatibility scan of live PythonAnywhere source.
No WSGI source disclosure, env, secrets, DB, order or provider requests.
"""
import ast,hashlib,os,re,urllib.error,urllib.request
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
BASE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES=("miniapp_server.py","pd_request_security.py","miniapp/templates/index.html")
def fetch(path,token):
 req=urllib.request.Request(API+path,method="GET",headers={"Authorization":"Token "+token})
 try:
  with urllib.request.urlopen(req,timeout=35) as r:return r.status,r.read(800000)
 except urllib.error.HTTPError as exc:return exc.code,b""
def check(ok,label):
 print("CHECK",label,"PASS" if ok else "BLOCK",flush=True)
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 docs={}
 for name in FILES:
  status,raw=fetch(BASE+name,token)
  print("FILE",name,"HTTP",status,"SHA256",hashlib.sha256(raw).hexdigest() if status==200 else "-",flush=True)
  if status!=200:raise RuntimeError("LIVE_READ_UNAVAILABLE")
  docs[name]=raw.decode("utf8")
 srv=docs["miniapp_server.py"]
 security=docs["pd_request_security.py"]
 html=docs["miniapp/templates/index.html"]
 ast.parse(srv);ast.parse(security)
 check("def auth():" in srv,"LIVE_TELEGRAM_AUTH_PRESENT")
 check("X-Telegram-Init-Data" in srv or "X-Telegram-Init-Data" in security,
       "TELEGRAM_HEADERS_PRESENT")
 check("@app.post('/api/order')" in srv,"LIVE_TELEGRAM_BOOKING_PRESENT")
 check("@app.get('/api/orders')" in srv,"LIVE_TELEGRAM_HISTORY_PRESENT")
 check(not re.search(r"@app\\.(?:get|post|route)\\(['\\\"]?/api/web/",srv),
       "WEB_API_ROUTE_NAMESPACE_NOT_OCCUPIED")
 check("initData" in html and "pdbPays" in html,"CURRENT_TELEGRAM_BOOKING_UI_PRESENT")
 # The WSGI configuration is outside these files. Its entry point is not
 # guessed, and no deployment/route attachment is attempted.
 print("BLOCK PRODUCTION_WEB_WSGI_ENTRY_NOT_VERIFIED",flush=True)
 print("BLOCK VERIFIED_EMAIL_DELIVERY_NOT_CONFIGURED",flush=True)
 print("BLOCK OLD_ORDERS_OWNERSHIP_MAPPING_NOT_MIGRATED",flush=True)
 print("BLOCK WEB_PAYMENT_PROVIDER_FLOW_NOT_TESTED",flush=True)
 print("WEB_COMPATIBILITY_READONLY_COMPLETE",flush=True)
 print("NO_PRODUCTION_WRITES_NO_DATABASE_NO_ORDERS_NO_PAYMENT",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print("WEB_AUDIT_FAILED",type(exc).__name__,flush=True)
  raise SystemExit(1)
