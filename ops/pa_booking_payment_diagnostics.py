"""Live read-only diagnosis of booking time and driver payment gate.
No customer DB queries, no writes, no production imports and no payment calls.
"""
import os,re,requests,hashlib
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
token="".join(re.sub(r"^Token\s+","",os.getenv("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token: raise SystemExit("NO_CREDENTIAL")
s=requests.Session();s.headers["Authorization"]="Token "+token
paths=["miniapp/templates/index.html","pd_trip_runtime_v4.py","pd_pilot_dispatch.py","pd_admin_console_v4.py","miniapp_server.py"]
for path in paths:
 r=s.get(base+path,timeout=40)
 if r.status_code!=200:print("READ_ERROR",path,r.status_code);continue
 t=r.content.decode("utf8")
 print("FILE",path,"bytes",len(r.content),"sha12",hashlib.sha256(r.content).hexdigest()[:12])
 if path.endswith(".html"):
  for key in ["id=\"time\"","id=\"pdbTime\"","function pdbSummary","async function pdbSendOrder","function pdbNewRequest"]:
   print("HTML_MARKER",key,"COUNT",t.count(key))
  for m in re.finditer(r'id="(?:time|pdbTime)"[^>]{0,200}',t):
   print("TIME_INPUT",re.sub(r'\s+',' ',m.group(0))[:200])
  for m in re.finditer(r'(?:pdbTime|["\x27]time["\x27]).{0,30}(?:value\s*=|setAttribute\()',t):
   print("TIME_WRITE_CONTEXT",re.sub(r'\s+',' ',t[max(0,m.start()-95):m.end()+130])[:270])
  for q in ["async function pdbSendOrder","function pdbSummary"]:
   ix=t.find(q)
   if ix!=-1:
    body=t[ix:ix+2800]
    print("UI_TIME_CHAIN",q,[(x,len(list(re.finditer(x,body)))) for x in [r"trip_time",r"pdbTime",r"12:00",r"pdbSummary"]])
 else:
  for pattern in [r"payment_status[^\n]{0,110}Оплачено",r"Оплачено[^\n]{0,110}payment_status",r"Дождитесь подтверждённой оплаты",r"Подтвердите оплату",r"подтвердите оплату",r"target\s*==\s*['\"]В пути",r"action\s*==\s*['\"]start"]:
   matches=list(re.finditer(pattern,t,re.I))
   print("PAYMENT_RULE",path,pattern,"matches",len(matches))
   for m in matches[:3]:
    clean=re.sub(r'\s+',' ',t[max(0,m.start()-120):m.end()+120])
    print("RULE_CONTEXT",clean[:370])
print("DIAGNOSIS_READONLY_OK")
