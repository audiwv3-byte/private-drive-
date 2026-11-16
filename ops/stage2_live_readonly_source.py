"""Production stage 2 registration read-only audit. Prints strictly selected source
lines, no database or customer records. Requires PythonAnywhere API GET token.
"""
import os,re,urllib.request,hashlib
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
def fetch(path):
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 req=urllib.request.Request(base+path,headers={"Authorization":"Token "+token},method="GET")
 with urllib.request.urlopen(req,timeout=40) as r:
  return r.read(700000).decode("utf8")
def main():
 for name in ("pd_onboarding.py","miniapp/templates/index.html"):
  s=fetch(name);lines=s.splitlines()
  print("FILE",name,"HASH",hashlib.sha256(s.encode()).hexdigest(),"LINES",len(lines))
  if name=="pd_onboarding.py":ranges=[(5,23),(76,100),(115,140),(140,173)]
  else:ranges=[(305,340),(460,492)]
  for a,b in ranges:
   print("RANGE",a,b)
   for n in range(a,b+1):
    if n>len(lines):continue
    line=lines[n-1]
    if re.search(r"(TOKEN|PASSWORD|SECRET|API_KEY)",line,re.I):continue
    print(f"{n}: {line[:1000]}")
 print("STAGE2_READ_ONLY_AUDIT_COMPLETE")
if __name__=="__main__":main()
