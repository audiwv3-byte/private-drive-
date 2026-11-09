"""Read-only verification of the existing PRIVATE DRIVE onboarding before design updates."""
import hashlib,os,re,requests
token=re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I)
token="".join(token.split())
s=requests.Session();s.headers["Authorization"]="Token "+token
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
p="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
r=s.get(base+"/files/path"+p,timeout=35);r.raise_for_status();b=r.content
h=b.decode("utf-8-sig")
print("LIVE_SOURCE_SHA256",hashlib.sha256(b).hexdigest(),"length",len(b))
for x in ('<div id="pdObLanguage"','<div id="pdObRole"','function pdChooseInitialLanguage','function pdShowOnboarding','pd-welcome-20261109'):
 i=h.find(x);print("STRUCTURE",x,i,repr(h[i:i+750]) if i>=0 else "not_found")
for asset in ('/assets/private-drive-night.png','/assets/private-drive-official-logo.jpeg'):
 try:
  r=requests.get("https://wilsonpark.pythonanywhere.com"+asset,timeout=25,stream=True);print("PUBLIC_ASSET",asset,r.status_code,r.headers.get("content-type"),r.headers.get("content-length"));r.close()
 except Exception as e:print("PUBLIC_ASSET",asset,"unavailable",type(e).__name__)
print("READ_ONLY_COMPLETE")
