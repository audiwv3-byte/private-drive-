"""Read-only audit of live PRIVATE DRIVE language button CSS and markup."""
import hashlib,os,re,requests
token=re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I)
token="".join(token.split())
root="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
s=requests.Session();s.headers.update({"Authorization":"Token "+token})
r=s.get(root+"/files/path"+path,timeout=40);r.raise_for_status()
html=r.content.decode("utf-8-sig")
print("LIVE_SHA256",hashlib.sha256(r.content).hexdigest(),"bytes",len(r.content))
for needle in (".pd-welcome-choices{", ".pd-welcome-choices button{", ".pd-welcome-choices button[aria-pressed", '<div class="pd-ob-language-options pd-welcome-choices"', "::before", "→"):
 print("OCCURRENCES",repr(needle),html.count(needle))
 if needle=="::before":
  for m in list(re.finditer(re.escape(needle),html))[-15:]:
   p=m.start()
   print("PSEUDO_CONTEXT",repr(html[max(0,p-270):p+160]))
 else:
  pos=html.find(needle)
  if pos>=0:print("MATCH_CONTEXT",repr(html[max(0,pos-250):pos+650]))
print("AUDIT_READ_ONLY_OK")

for needle in (":before",":after","content:'→'","content:\"→\"","content:'➜'","content:'➔'","pd-welcome-choices button>","pd-ob-language-options button:","pd-welcome-choices button:"):
  matches=list(re.finditer(re.escape(needle),html))
  print("ARROW_CSS_MATCH",repr(needle),"count",len(matches))
  for m in matches[:6]:
    p=m.start()
    print("ARROW_CONTEXT",repr(html[max(0,p-240):p+250]))
