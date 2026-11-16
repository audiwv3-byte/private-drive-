"""Independent GET-only verification of active stage2 disabled button release."""
import hashlib,os,re,urllib.request
EXPECTED="d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0"
BACKEND="7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b"
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
SITE="https://wilsonpark.pythonanywhere.com/"
def check(ok,label):
 if not ok:raise RuntimeError("FAIL_"+label)
 print("PASS",label,flush=True)
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 def get(path):
  req=urllib.request.Request(BASE+path,method="GET",headers={"Authorization":"Token "+token})
  with urllib.request.urlopen(req,timeout=40) as r:
   check(r.status==200,"REMOTE_HTTP_"+path.replace("/","_"));return r.read(800000)
 html=get("miniapp/templates/index.html")
 print("DEPLOYED_HTML_SHA256",hashlib.sha256(html).hexdigest(),flush=True)
 check(hashlib.sha256(html).hexdigest()==EXPECTED,"EXACT_DEPLOYED_HTML_SHA256")
 code=get("pd_onboarding.py")
 check(hashlib.sha256(code).hexdigest()==BACKEND,"SERVER_APPROVAL_BACKEND_UNCHANGED_SHA")
 for key,needle in {
  "CSS_GREY_DISABLED":b"pd-stage2-approval-disabled-visual",
  "GREY_BUTTON_CLASS":b"pd-approval-blocked:disabled",
  "EXPLICIT_REASON":b"pd-approval-blocked-reason",
  "BLOCKED_APPROVAL_STATUS_EXPRESSION":b"a.status==='stage2'",
  "TWO_STAGE_EXPLANATION":b"function pdStage2ApprovalHint(a,missingPhotos)",
  "PILOT_GPS_PRESERVED":b"pd-pilot-cockpit-adapter-stage-js",
  "DISPATCH_ORDER_ASSET_PRESERVED":b"/assets/pd-admin-console-v4.js",
  "PASSENGER_PAYMENT_FORM_PRESERVED":b'id="pdbPays"'
 }.items():check(needle in html,key)
 with urllib.request.urlopen(urllib.request.Request(SITE,headers={"User-Agent":"PD-Independent-DisabledApproval-GET/1"}),timeout=40) as r:
  status=r.status;public=r.read(800000)
 check(status==200,"PUBLIC_SITE_HTTP_200")
 check(b"pd-stage2-approval-disabled-visual" in public and b"pd-approval-blocked-reason" in public,
       "PUBLIC_SITE_NEW_DISABLED_BUTTON_VISIBLE_IN_SOURCE")
 print("STAGE2_VISUAL_POSTRELEASE_INDEPENDENT_VERIFIED",flush=True)
 print("NO_REMOTE_WRITES_NO_USERS_ORDERS_OR_PAYMENTS",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("POSTRELEASE_VERIFICATION_FAILED",type(e).__name__,str(e)[:120],flush=True)
  raise SystemExit(1)
