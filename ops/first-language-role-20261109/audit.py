"""Read-only audit of live first-launch onboarding sequence in PRIVATE DRIVE."""
import requests,os,re,hashlib
token=re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I);token="".join(token.split())
s=requests.Session();s.headers["Authorization"]="Token "+token
base="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
r=s.get(base+"/files/path"+path,timeout=35);r.raise_for_status()
page=r.content.decode("utf-8-sig");print("LIVE_SHA256",hashlib.sha256(r.content).hexdigest(),"bytes",len(r.content))
for token in ("function pdOnboardingStart(user){","function pdChooseInitialLanguage(lang){","function pdShowOnboarding(stage){","window.pdWelcomeSelect=function(lang){","window.pdWelcomeContinue=function(manual){","function pdSwitchLanguage(","pdWelcomeManualPending","pdWelcomeLanguageConfirmed","pdOnboardingStage","id=\"pdObLanguage\""):
 positions=[m.start() for m in re.finditer(re.escape(token),page)]
 print("CODE_MARKER",repr(token),"positions",positions[:9])
 for i in positions[:2]:
  print("CODE_CONTEXT",repr(page[max(0,i-180):i+2200]))
print("READ_ONLY_COMPLETED")
