"""Single-file guarded production cache privacy patch with immediate rollback."""
from __future__ import annotations
import ast,hashlib,os,re,sys,time,requests

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
SNAPSHOT="/home/wilsonpark/private_drive_backups/snapshot_20261106T085712Z_9458f4"
FILE="miniapp_server.py"
OLD="""@app.after_request
def private_response_cache(response):
    if request.path.lower().startswith(('/static/', '/api/pilot', '/api/admin/', '/api/payment')):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Vary'] = 'X-Telegram-Init-Data'
    return response"""
NEW="""@app.after_request
def private_response_cache(response):
    # Never allow authenticated API responses to be reused across Telegram identities.
    path = request.path.lower()
    if path.startswith('/api/') or path.startswith('/static/'):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.vary.add('X-Telegram-Init-Data')
    return response"""
EXPECTED_SHA12="57741aaacc45"
EXPECTED_BYTES=52879

def main():
 token="".join(re.sub(r"^Token\s+","",os.getenv("PA_API_TOKEN","").strip(),flags=re.I).split())
 if not token:raise RuntimeError("AUTH_NOT_CONFIGURED")
 s=requests.Session();s.headers["Authorization"]="Token "+token
 path="/files/path"+ROOT+"/"+FILE
 backup="/files/path"+SNAPSHOT+"/"+FILE
 def get(remote):
  r=s.get(BASE+remote,timeout=40)
  if r.status_code!=200:raise RuntimeError("SOURCE_READ_FAILED HTTP "+str(r.status_code))
  return r.content
 def put(data):
  r=s.post(BASE+path,files={"content":("privacy-patch.py",data,"text/x-python")},timeout=45)
  if r.status_code!=200:raise RuntimeError("WRITE_FAILED HTTP "+str(r.status_code))
 def reload_site():
  r=s.post(BASE+"/webapps/wilsonpark.pythonanywhere.com/reload/",timeout=60)
  if r.status_code not in (200,201,204):raise RuntimeError("RELOAD_FAILED HTTP "+str(r.status_code))
 def api_probe():
  for endpoint in ("/api/orders","/api/trip/42","/api/driver/work","/api/admin/orders"):
   r=requests.get(SITE+endpoint,timeout=20,headers={"Cache-Control":"no-cache"})
   if r.status_code not in (401,403):raise RuntimeError("AUTH_BOUNDARY_FAILED "+endpoint+" HTTP "+str(r.status_code))
   if "no-store" not in r.headers.get("Cache-Control",""):
    raise RuntimeError("CACHE_HEADER_MISSING "+endpoint)
   if "X-Telegram-Init-Data" not in r.headers.get("Vary",""):
    raise RuntimeError("IDENTITY_VARY_HEADER_MISSING "+endpoint)
   print("ACCESS_CACHE_VERIFIED",endpoint,r.status_code)
 original=get(path);snap=get(backup)
 if original!=snap:raise RuntimeError("LIVE_SOURCE_DIFFERS_FROM_VERIFIED_SNAPSHOT")
 if len(original)!=EXPECTED_BYTES or hashlib.sha256(original).hexdigest()[:12]!=EXPECTED_SHA12:
  raise RuntimeError("UNEXPECTED_LIVE_SOURCE_VERSION")
 source=original.decode("utf8")
 if source.count(OLD)!=1 or NEW in source:raise RuntimeError("ANCHOR_NOT_EXACTLY_ONCE")
 modified=source.replace(OLD,NEW,1).encode("utf8")
 ast.parse(modified.decode("utf8"),filename=FILE)
 print("PRECHECK_OK","snapshot_verified",True,"before_sha12",hashlib.sha256(original).hexdigest()[:12],
       "after_sha12",hashlib.sha256(modified).hexdigest()[:12])
 written=False
 try:
  if get(path)!=original:raise RuntimeError("CONCURRENT_WRITE_DETECTED")
  put(modified);written=True
  if get(path)!=modified:raise RuntimeError("READBACK_MISMATCH")
  reload_site()
  api_probe()
  if get(path)!=modified:raise RuntimeError("SOURCE_CHANGED_AFTER_RELOAD")
  print("PRODUCTION_PRIVACY_CACHE_PATCH_SUCCESS")
 except Exception as error:
  print("PATCH_FAILED_ROLLING_BACK",str(error),file=sys.stderr)
  if written:
   current=get(path)
   if current!=modified:raise RuntimeError("ROLLBACK_BLOCKED_CONCURRENT_MODIFICATION") from error
   put(original)
   if get(path)!=original:raise RuntimeError("ROLLBACK_READBACK_FAILED") from error
   reload_site()
   print("ROLLBACK_VERIFIED")
  raise

if __name__=="__main__":
 try:main()
 except Exception as e:
  print("DEPLOY_ERROR",str(e),file=sys.stderr)
  sys.exit(1)
