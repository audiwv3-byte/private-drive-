"""Read-only inspect known dispatcher render function in deployed HTML.

Print only function text (bounded, secret-pattern redacted), no personal records,
no DB access; data comes from GET of source template only.
"""
import hashlib,os,re,requests
from urllib.parse import quote
BASE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
URL="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(BASE+"miniapp/templates/index.html",safe="/")
token="".join(os.environ.get("PA_API_TOKEN","").strip().split())
if not token: raise SystemExit("No token")
r=requests.get(URL,headers={"Authorization":"Token "+token},timeout=35)
r.raise_for_status()
expected="d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0"
if hashlib.sha256(r.content).hexdigest()!=expected:
    raise SystemExit("Live HTML source has changed")
s=r.content.decode("utf-8")
start=s.find("async function pdLoadDriverApplications(){")
if start<0:raise SystemExit("Unknown dispatcher render function")
end=s.find("\n}",start)
if end<0 or end-start>7000:raise SystemExit("Unexpected dispatcher function length")
frag=s[start:end+2]
for i,line in enumerate(frag.splitlines()):
    if any(t in line.lower() for t in ("token","secret","password","api_key")):
        print("ADMIN_RENDER",i,"[REDACTED]")
    else:
        print("ADMIN_RENDER",i,line[:1300])
print("HTML_INSPECT_GET_ONLY")
