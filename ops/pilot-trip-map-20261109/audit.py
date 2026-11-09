"""Read-only audit for driver live map and full-screen behavior.
Only source files & public JS asset responses, no order/customer data.
"""
import os,re,requests,hashlib
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
s=requests.Session();s.headers["Authorization"]="Token "+token
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
paths=["miniapp/templates/index.html","pd_trip_runtime_v4.js","pd_pilot_cabinet_v4.js","pd_trip_runtime_v4.py"]
for path in paths:
 r=s.get(base+path,timeout=35);r.raise_for_status()
 h=r.content.decode("utf-8-sig")
 print("SOURCE",path,"sha256",hashlib.sha256(r.content).hexdigest(),"bytes",len(r.content))
 if path.endswith(".html"):
  for needle in ('function pdPilotWork()', "await api('/api/driver/work/'+o.id+'/status'",'function pdDriverLoad()', 'async function pdDriverLoad()', 'pdSetRole(\'driver\')', 'id="step13"', 'pd-trip-runtime-v4.js','pd-pilot-cabinet-v4.js','function pdSimpleDialog','L.map','leaflet.css','leaflet.js'):
   i=h.find(needle);print("MARKER",path,repr(needle),"count",h.count(needle),"pos",i)
   if i>=0:print("CONTEXT",path,repr(needle),repr(h[max(0,i-170):i+700]))
 if path.endswith(".html"):
  i=h.find("async function pdDriverLoad()")
  if i>=0:print("DRIVER_LOAD_CODE",repr(h[i:i+4100]))
 if path=="pd_trip_runtime_v4.js":
  print("RUNTIME_JS",repr(h[7100:19000]))
 if path=="pd_pilot_cabinet_v4.js":
  print("PILOT_JS",repr(h[3900:10500]))
 if path=="pd_trip_runtime_v4.py":
  for needle in ("def view(", "def identity(", "@app.get('/api/trip/<int:oid>')"):
   i=h.find(needle);print("CONTEXT",path,repr(needle),repr(h[max(0,i-150):i+3100]) if i>=0 else "not found")
for asset in ["/assets/pd-trip-runtime-v4.js","/assets/pd-pilot-cabinet-v4.js"]:
 r=requests.get("https://wilsonpark.pythonanywhere.com"+asset,timeout=25)
 print("PUBLIC_ASSET",asset,"status",r.status_code,"bytes",len(r.content),"sha256",hashlib.sha256(r.content).hexdigest(),"mime",r.headers.get("content-type"))
print("AUDIT_DONE reads_only=true")
