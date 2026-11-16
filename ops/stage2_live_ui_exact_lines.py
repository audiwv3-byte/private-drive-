"""Read-only extracts only driver admin row code (no user data)."""
import os,re,urllib.request
t=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
u="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
with urllib.request.urlopen(urllib.request.Request(u,method="GET",headers={"Authorization":"Token "+t}),timeout=40) as r:s=r.read(700000).decode()
for n in (485,486):
 print("CODE_LINE",n,s.splitlines()[n-1][:9000])
print("DONE_READ_ONLY")
