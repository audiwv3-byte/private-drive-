"""Read-only deployment compatibility probe. Prints booleans/counts, never source or secrets."""
import os, re, hashlib, requests, pathlib, sys
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
TOKEN="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
if not TOKEN:
    raise SystemExit("PREFLIGHT_BLOCKED: missing PA_API_TOKEN")
S=requests.Session(); S.headers["Authorization"]="Token "+TOKEN
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+ROOT+"/"
FILES={
"miniapp/templates/index.html":[
    ("temp_legacy","🌡️ Температура в салоне<br>"),
    ("temp_style",'<style id="pdTemperatureLayoutFix">'),
    ("pilot_css","#pdPilotPassenger{display:none!important}"),
    ("pilot_button",'id="pdPilotPassenger"'),
],
"pd_fixed_prices.py":[
    ("fixed_old","return '190.00' if data.get('roundtrip') else '130.00'"),
    ("fixed_new","return '200.00' if data.get('roundtrip') else '130.00'"),
],
"pd_pilot_cabinet_v4.js":[
    ("pilot_old","passenger.classList.toggle('hidden',!user.registered);"),
    ("pilot_new","passenger.classList.add('hidden');"),
],
"pd_trip_runtime_v4.js":[
    ("gps_old","function cleanDialog(){if(map)map.remove();"),
    ("gps_new","function cleanDialog(){stopPosition();closing(false);if(map)map.remove();"),
]
}
passed=True
for path,patterns in FILES.items():
    response=S.get(BASE+path,timeout=35)
    if response.status_code!=200:
        print("PREFLIGHT",path,"HTTP",response.status_code)
        passed=False
        continue
    source=response.content.decode("utf-8",errors="strict")
    print("PREFLIGHT",path,"bytes",len(response.content),"sha256",hashlib.sha256(response.content).hexdigest()[:16])
    for key,pattern in patterns:
        print("ANCHOR",path,key,source.count(pattern))
print("PREFLIGHT_READ_ONLY_COMPLETE")
if not passed:sys.exit(2)
