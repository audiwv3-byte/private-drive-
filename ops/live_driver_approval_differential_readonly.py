"""Read only: focused live pilot approval and admin stats feature inventory.
Prints code structure and matching short code lines, no data/environment files.
"""
import os,re,urllib.request
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES={"DRIVER":"pd_onboarding.py","DISPATCH":"pd_admin_console_v4.js","UI":"miniapp/templates/index.html"}
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 targets={
  "DRIVER":[r"def pd_driver_apply",r"def pd_driver_decide",r"def pd_dispatcher_replace",r"photo.*(replace|review)",r"missing_document_sides",r"status='pending'",r"status=excluded.status",r"UPDATE SET image",r"stored.intersection",r"ACTIVE_SIDES",r"core.is_admin",r"document_sides"],
  "DISPATCH":[r"let root=",r"async function renderList",r"pendingRender",r"if\(busy",r"const stats=",r"for\\(const\\[key,label\\]of stats",r"const search=el",r"const date=el"],
  "UI":[r"function pdDocumentRefresh",r"async function pdChooseDocument",r"async function pdLoadDriverApplications",r"missing_document_sides",r"b.disabled=a.status===target",r"pdPilotCockpit",r"pd-pilot-cockpit-adapter-stage-js"]
 }
 for label,path in FILES.items():
  req=urllib.request.Request(BASE+path,headers={"Authorization":"Token "+token},method="GET")
  with urllib.request.urlopen(req,timeout=40) as r:text=r.read(700000).decode("utf8")
  lines=text.splitlines()
  print("FILE",label,"LINECOUNT",len(lines),flush=True)
  if label=="DRIVER":
   for n in range(95,min(174,len(lines)+1)):
    v=lines[n-1]
    if not re.search(r"secret|token|password|API_KEY",v,re.I):print("DETAIL",label,n,v[:230],flush=True)
 for pat in targets[label]:
   matches=[(i+1,v[:210]) for i,v in enumerate(lines) if re.search(pat,v,re.I)]
   print("PATTERN",label,pat,"COUNT",len(matches),flush=True)
   for number,v in matches[:4]:
    if re.search(r"API_KEY|CLIENT_SECRET|BOT_TOKEN|PASSWORD|Authorization.*Token",v,re.I):
     continue
    print("SOURCE",label,number,v,flush=True)
 print("NO_PRIVATE_DATA_NO_DB_NO_WRITES",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as err:
  print("AUDIT_FAILURE",type(err).__name__,flush=True)
  raise SystemExit(1)
