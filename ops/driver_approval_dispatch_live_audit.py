"""Read-only live compatibility check before driver/dispatcher UI update.

No reading records, SQLite, environment variables or personal documents;
only PythonAnywhere GET source files and SHA256 metadata.
"""
import hashlib,os,re,urllib.error,urllib.request
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES={
"pd_onboarding.py":("def pd_driver_decide(", "INSERT INTO pd_driver_documents("),
"pd_admin_console_v4.js":("function renderList(", "pdAdminStatsV4"),
"miniapp/templates/index.html":("function pdLoadDriverApplications(", "function pdDocumentRefresh("),
}
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 for path,anchors in FILES.items():
  request=urllib.request.Request(BASE+path,method="GET",headers={"Authorization":"Token "+token})
  try:
   with urllib.request.urlopen(request,timeout=50) as response:
    source=response.read(700000);status=response.status
  except urllib.error.HTTPError as ex:
   print("FILE",path,"HTTP",ex.code,flush=True)
   raise RuntimeError("UNREADABLE_REMOTE_SOURCE_"+path)
  if status!=200:raise RuntimeError("FAILED_REMOTE_SOURCE")
  value=source.decode("utf8")
  print("FILE",path,"HTTP",status,"SHA256",hashlib.sha256(source).hexdigest(),"BYTES",len(source),flush=True)
  for anchor in anchors:
   if anchor not in value:raise RuntimeError("MISSING_ANCHOR_"+path)
  print("PASS SOURCE_ANCHORS",path,flush=True)
 print("APPROVAL_DISPATCHER_LIVE_COMPATIBILITY_READONLY_PASS",flush=True)
 print("NO_ORDERS_NO_USER_RECORDS_NO_PAYMENT_NO_FILE_WRITES",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("COMPATIBILITY_BLOCKED",type(e).__name__,str(e)[:100],flush=True)
  raise SystemExit(1)
