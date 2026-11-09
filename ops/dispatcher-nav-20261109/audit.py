"""Read-only audit of live dispatcher lower nav and client-mode role switch.
Only inspect template source. Do not query or modify passenger/order databases.
"""
import re,os,hashlib,requests
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
s=requests.Session();s.headers["Authorization"]="Token "+token
url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
r=s.get(url,timeout=50);r.raise_for_status();b=r.content;html=b.decode("utf-8-sig")
print("LIVE_SHA256",hashlib.sha256(b).hexdigest(),"BYTES",len(b))
patterns=["function pdSetRole(","pdSetRole('client')",'data-mode="client"','id="mainNav"',"Как клиент","Как пассажир","Диспетчерская","body.admin-home","pd-role-admin","pd-role-visibility",'class="nav"',"mainNav"]
for key in patterns:
 pos=[m.start() for m in re.finditer(re.escape(key),html)]
 print("MARKER",repr(key),"count",len(pos),"positions",pos[:8])
 for at in pos[:3]:print("SNIPPET",repr(key),repr(html[max(0,at-340):at+1700]))
print("AUDIT_OK production_writes=0 database_reads=0")
