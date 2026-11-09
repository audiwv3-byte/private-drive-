"""Read-only audit of unwanted automatic location prompt in live PRIVATE DRIVE Mini App.
Inspect template source and callsites only; do not read or write any user database.
"""
import hashlib,os,re,requests
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
s=requests.Session();s.headers["Authorization"]="Token "+token
url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
r=s.get(url,timeout=50);r.raise_for_status();data=r.content;h=data.decode("utf-8-sig")
print("LIVE_SHA256",hashlib.sha256(data).hexdigest(),"BYTES",len(data))
keys=["Показать вас на карте?","Определим ваше местоположение","Указать адрес вручную","Показать меня на карте","pd-location","pdLocation","geo-consent","geoConsent","location-consent","pdbAutoLocate","pdbLocate(false)","pdbLocate(true)","pdPrompt","locationPrompt","pdbGeo","pdGeo","requestLocation","geo-intro","pd-location-dialog"]
for k in keys:
 pos=[m.start() for m in re.finditer(re.escape(k),h,re.I)]
 print("MARKER",repr(k),"total",len(pos),"positions",pos[:15])
 for i in pos[:6]:
  print("SOURCE_CONTEXT",repr(k),repr(h[max(0,i-800):i+1600]))
print("AUDIT_COMPLETE no_writes=1")
