"""No-write check of LIVE order visibility and payment/time code. No customer records."""
import ast,hashlib,os,re,requests
root="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
token="".join(re.sub(r"^Token\s+","",os.getenv("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token:raise SystemExit("NO_TOKEN")
session=requests.Session();session.headers["Authorization"]="Token "+token
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+root+"/"
paths=["miniapp_server.py","pd_pilot_dispatch.py","pd_trip_runtime_v4.py","pd_admin_console_v4.py","pd_onboarding.py","miniapp/templates/index.html"]
for path in paths:
 r=session.get(base+path,timeout=40)
 if r.status_code!=200:
  print("FILE_UNAVAILABLE",path,r.status_code);continue
 t=r.content.decode("utf-8")
 print("FILE",path,"size",len(r.content),"sha12",hashlib.sha256(r.content).hexdigest()[:12])
 if path.endswith(".py"):
  tree=ast.parse(t)
  lines=t.splitlines()
  for n in ast.walk(tree):
   if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(any(term in ast.get_source_segment(t,d) for term in ("/api/orders","/api/admin/orders","/api/trip/","/api/driver/work","/api/admin/console/orders","/api/admin/pilot-assignments","/api/payment/")) for d in n.decorator_list):
    body="\n".join(lines[n.lineno-1:n.end_lineno])
    print("ENDPOINT_FUNCTION",path,n.name,"lines",n.lineno,n.end_lineno,
          "has_auth",bool(re.search(r"\bauth\(|\bidentity\(",body)),
          "has_ownership",bool(re.search(r"telegram_id\s*=\s*\?|telegram_id'\]\s*!=|telegram_id'\]\s*==|telegram_id'\],|uid not in",body)),
          "has_admin",bool(re.search(r"is_admin\s*\(|\badmin\s*\(",body)),
          "has_pilot",bool(re.search(r"pilot_id\s*=\s*\?|pilot\s*\(",body)))
    for line in body.splitlines():
     if any(key in line for key in ("SELECT "," WHERE ","PermissionError","auth()","identity()","is_admin(")):
      safe=line.strip()
      if len(safe)>420:safe=safe[:420]
      print("ACL_LINE",safe)
  if path=="pd_trip_runtime_v4.py":
   for q in ["Дождитесь подтверждённой оплаты","if r['payment_status']","if r[\"payment_status\"]"]:
    i=t.find(q);print("PAYMENT_GUARD",q,"count",t.count(q),"context",re.sub(r"\s+"," ",t[max(0,i-150):i+160]) if i>=0 else "-")
 else:
  for key in ["id=\"pdbTime\"","value=\"12:00\"","function pdbSummary","async function pdbSendOrder","/api/orders","/api/admin/orders","/api/trip/"]:
   print("HTML_MARKER",key,t.count(key))
  for m in re.finditer(r"\$\('pdbTime'\)\.value\s*=|document\.getElementById\(['\"]pdbTime['\"]\)\.value\s*=|['\"]12:00['\"]",t):
   print("TIME_WRITE",re.sub(r"\s+"," ",t[max(0,m.start()-75):m.end()+100])[:240])
  for q in ["async function pdbSendOrder","function pdbSummary"]:
   i=t.find(q);print("TIME_CHAIN",q,"exists",i>=0,"trip_time",("trip_time" in t[i:i+2600]) if i>=0 else False)
  for marker in ["/api/orders","/api/admin/orders","/api/driver/work","pdOnboardingUser","pdPassengerView","pdCurrentTrip"]:
   matches=list(re.finditer(re.escape(marker),t))
   print("HTML_USAGE",marker,"count",len(matches))
   for m in matches[:6]:
    print("HTML_USAGE_CONTEXT",marker,re.sub(r"\s+"," ",t[max(0,m.start()-160):m.end()+240])[:420])
  for marker in ["localStorage","sessionStorage","lastOrder","currentOrder"]:
   print("CLIENT_STATE_MARKER",marker,"count",t.count(marker))
print("NO_WRITE_AUDIT_COMPLETE")
