"""Independent postrelease verification: PythonAnywhere GET only.
No changes to source, orders, payments, user data or server settings.
"""
import hashlib,os,re,urllib.error,urllib.request
EXPECTED="3e993f4d9bd957d8c02e5e364d4c65036b99ee2d17cc21ac8d1dbb6d859b1425"
REMOTE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
PUBLIC="https://wilsonpark.pythonanywhere.com/"
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 request=urllib.request.Request(REMOTE,headers={"Authorization":"Token "+token},method="GET")
 with urllib.request.urlopen(request,timeout=45) as r:
  data=r.read(700000);assert r.status==200
 actual=hashlib.sha256(data).hexdigest()
 print("LIVE_SHA256",actual,flush=True)
 if actual!=EXPECTED:raise RuntimeError("DEPLOYED_HTML_SHA_MISMATCH")
 print("PASS INDEPENDENT_LIVE_SHA256_MATCH",flush=True)
 checks={
  "PILOT_COCKPIT_SCRIPT":b"pd-pilot-cockpit-stage-js" in data,
  "PILOT_COCKPIT_ADAPTER":b"pd-pilot-cockpit-adapter-stage-js" in data,
  "PILOT_COCKPIT_STYLE":b"pd-pilot-cockpit-stage-css" in data,
  "LEGACY_PASSENGER_FORM":b'id="pdbPays"' in data,
  "LEGACY_DRIVER_HOST":b'id="pdPilotWork"' in data,
  "LEGACY_ADMIN_SCRIPT":b"/assets/pd-admin-console-v4.js" in data,
  "LEGACY_TRIP_RUNTIME":b"/assets/pd-trip-runtime-v4.js" in data,
 }
 for k,v in checks.items():
  if not v:raise RuntimeError("MISSING_"+k)
  print("PASS",k,flush=True)
 with urllib.request.urlopen(urllib.request.Request(PUBLIC,headers={"User-Agent":"PrivateDrive-ReadonlyPostrelease/1"}),timeout=35) as r:
  page=r.read(700000);status=r.status
 print("PUBLIC_HTTP",status,flush=True)
 if status!=200 or b"pd-pilot-cockpit-adapter-stage-js" not in page:
  raise RuntimeError("PUBLIC_COCKPIT_MARKER_NOT_VISIBLE")
 print("PASS PUBLIC_SITE_SERVES_NEW_COCKPIT",flush=True)
 print("POSTRELEASE_GPS_PILOT_HTML_VERIFIED_NO_MUTATION",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("POSTRELEASE_AUDIT_FAILED",type(e).__name__,str(e)[:120],flush=True)
  raise SystemExit(1)
