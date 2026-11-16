"""GET-only compare current live 2-step onboarding and dispatcher wiring. Never read DB."""
import hashlib,os,re,urllib.request
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
paths=["pd_onboarding.py","miniapp/templates/index.html","miniapp_server.py"]
token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
for path in paths:
 req=urllib.request.Request(BASE+path,headers={"Authorization":"Token "+token},method="GET")
 with urllib.request.urlopen(req,timeout=40) as r:
  source=r.read(800000).decode("utf8")
 print("FILE",path,"SHA256",hashlib.sha256(source.encode()).hexdigest(),"LINES",len(source.splitlines()))
 lines=source.splitlines()
 if path=="pd_onboarding.py":
  ranges=[(1,38),(62,80),(88,98),(120,172)]
 elif path=="miniapp/templates/index.html":
  ranges=[(323,344),(475,493)]
 else:
  anchors=[i+1 for i,l in enumerate(lines) if "pd_onboarding.register" in l or "import pd_onboarding" in l]
  ranges=[(max(1,i-5),min(i+8,len(lines))) for i in anchors]
 for start,end in ranges:
  print("RANGE",start,end)
  for n in range(start,min(len(lines),end)+1):
   # Source code only, no user database or secrets; mask likely credentials.
   item=lines[n-1]
   if re.search(r"PASSWORD|SECRET|API_TOKEN|STRIPE_KEY",item,re.I):continue
   print(f"L{n}: {item[:11000]}")
 print("END_FILE",path)
print("ISSUE30_LIVE_READONLY_AUDIT_SUCCESS")
