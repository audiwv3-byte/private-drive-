"""Read-only source inspection of duplicate contacts and legal links in the live
PRIVATE DRIVE passenger profile. Never inspect any user records or databases."""
import os,re,hashlib,requests
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
s=requests.Session();s.headers["Authorization"]="Token "+token
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
f="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
r=s.get(base+f,timeout=40);r.raise_for_status()
src=r.content.decode("utf-8-sig")
print("LIVE_HASH",hashlib.sha256(r.content).hexdigest(),"SIZE",len(r.content))
for title,needle,after in [
 ("HEADER",'class="pd-privacy-bar"','</header>'),
 ("PROFILE_HEAD",'<section class="panel hidden" id="step14">','<div id="pdProfilePageHome">'),
 ("PROFILE_CARD",'<div class="pdb-price" id="pdbProfile">','<button type="button" id="pdbTelegramRegister"'),
 ("GLOBAL_FOOTER",'<footer class="pd-contact-footer','</footer>')
]:
 i=src.find(needle);j=src.find(after,i+len(needle)) if i>=0 else -1
 print("BLOCK",title,"start",i,"end",j,repr(src[i:j+len(after)][:3800]) if j>i>=0 else "NOT_FOUND")
for k in ["pd-privacy-notice","Вопросы и удаление данных","Политика конфиденциальности","Условия поездки и оплаты","eurobaltictransfer@gmail.com","pd-contact-footer"]:
 print("COUNT",k,src.count(k))
print("AUDIT_SUCCESS reads_only=True")
