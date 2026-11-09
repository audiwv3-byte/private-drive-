"""Read-only inspection of duplicate legal links in the passenger profile.
Only source text is inspected; no users, orders, tokens or databases output.
"""
import hashlib,os,re,requests
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
s=requests.Session();s.headers["Authorization"]="Token "+token
path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+path
r=s.get(url,timeout=50);r.raise_for_status()
b=r.content;h=b.decode("utf-8-sig")
print("LIVE_SHA256",hashlib.sha256(b).hexdigest(),"BYTES",len(b))
for title,start,end in [
("HEADER",'<div class="pd-privacy-bar">','</header>'),
("PROFILE",'<section class="panel hidden" id="step14">','<div id="pdProfilePageHome">'),
("PROFILE_ALT",'<section id="step14"','<div id="pdProfilePageHome">')
]:
 a=h.find(start);z=h.find(end,a) if a>=0 else -1
 print("SOURCE_BLOCK",title,"start",a,"end",z,"text",repr(h[a:z][:3200]) if a>=0 and z>a else "")
for term in ("Политика конфиденциальности","Условия поездки и оплаты","Вопросы и удаление данных"):
 print("COUNTS",term,h.count(term))
print("AUDIT_COMPLETE")
