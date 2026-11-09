"""Read-only audit: inspect current passenger markup, consent requirements, and Telegram-only flow.
No records, no credentials printed, no production writes.
"""
import re,os,requests,hashlib
token="".join(re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I).split())
s=requests.Session();s.headers["Authorization"]="Token "+token
root="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+root+"miniapp/templates/index.html"
r=s.get(url,timeout=50);r.raise_for_status();b=r.content;h=b.decode("utf-8-sig")
print("LIVE_SHA256",hashlib.sha256(b).hexdigest(),"BYTES",len(b))
a=h.index('<form id="pdObPassenger"')
z=h.index('</form>',a)+7
print("PASSENGER_FORM",repr(h[a:z]))
for term in ('function pdRequirePhoneConsent','pdObTerms','pdObPhoneConsent','pdRegistrationManual','pdObManual','pdObPassenger','privacyConsent','termsConsent','pd-phone-consent','Согласен передать','Принимаю условия','pdbRegisterTelegram','async function pdRegisterPassengerTelegram','pd-telegram-first','pdbPhoneConsent'):
 p=[m.start() for m in re.finditer(re.escape(term),h,re.I)]
 print("FIND",term,len(p),p[:7])
 for i in p[:2]:
  print("CONTEXT",term,repr(h[max(0,i-200):i+1250]))
print("INSPECT_OK")
