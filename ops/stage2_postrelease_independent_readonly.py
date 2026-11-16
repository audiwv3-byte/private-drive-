"""Independent GET-only postrelease stage2 UI verification.

No writes or reading user data; verifies exact deployed HTML source digest,
previously installed pilot cockpit markers and public page content.
"""
import hashlib,os,re,urllib.request
SHA="6d78db07c62b31e7fcee9de55dc822a5c99250484aa7443ecc2af19fb54f88b2"
REMOTE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
URL="https://wilsonpark.pythonanywhere.com/"
def check(ok,label):
 if not ok:raise RuntimeError(label)
 print("PASS",label,flush=True)
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 req=urllib.request.Request(REMOTE,method="GET",headers={"Authorization":"Token "+token})
 with urllib.request.urlopen(req,timeout=45) as r:
  source=r.read(700000);check(r.status==200,"LIVE_SOURCE_HTTP_200")
 actual=hashlib.sha256(source).hexdigest()
 print("LIVE_STAGE2_SHA256",actual,flush=True)
 check(actual==SHA,"LIVE_STAGE2_SHA_MATCH")
 checks={
 "STAGE2_HINT_PRESENT":b"function pdStage2ApprovalHint(a,missingPhotos)" in source,
 "STAGE2_BUTTON_EXPLANATION":b"pda-stage2-hint" in source,
 "PILOT_GPS_COCKPIT_PRESERVED":b"pd-pilot-cockpit-adapter-stage-js" in source,
 "DISPATCH_ORDER_UI_PRESERVED":b"/assets/pd-admin-console-v4.js" in source,
 "PASSENGER_BOOKING_PRESERVED":b'id="pdbPays"' in source,
 "OLD_PAYMENT_OPTIONS_UNCHANGED":'data-method="Наличными"'.encode() in source
 }
 for label,value in checks.items():check(value,label)
 with urllib.request.urlopen(urllib.request.Request(URL,headers={"User-Agent":"Stage2-UI-ReadonlyPostrelease/1"}),timeout=40) as r:
  html=r.read(700000);status=r.status
 check(status==200,"PUBLIC_SITE_HTTP_200")
 check(b"function pdStage2ApprovalHint(a,missingPhotos)" in html,"PUBLIC_PAGE_STAGE2_CODE_VISIBLE")
 print("STAGE2_INDEPENDENT_POSTRELEASE_VERIFIED",flush=True)
 print("NO_RECORDS_OR_PRODUCTION_FILES_MUTATED",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("POSTRELEASE_FAILED",type(e).__name__,str(e)[:120],flush=True)
  raise SystemExit(1)
