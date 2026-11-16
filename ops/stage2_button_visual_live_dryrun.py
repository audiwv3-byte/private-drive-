"""GET-only live-HTML inspection and visual stage2 approval patch dry run.

Never changes user, application, payment or production files. Exact SHA guard.
Tests CSS/JS on temporary files and verifies server stage2 guard structure.
"""
import hashlib,os,re,urllib.request,pathlib,tempfile,subprocess
from html.parser import HTMLParser
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
HTML="miniapp/templates/index.html"
BACKEND="pd_onboarding.py"
SOURCE_SHA="6d78db07c62b31e7fcee9de55dc822a5c99250484aa7443ecc2af19fb54f88b2"
BACKEND_SHA="7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b"
STYLE="""<style id="pd-stage2-approval-disabled-visual">
/* Only disabled approval buttons in the dispatcher driver-applications cards. */
.pd-driver-application button.pd-approval-blocked:disabled {
  background:#515151 !important;
  color:#fff !important;
  border:2px solid #969696 !important;
  opacity:1 !important;
  cursor:not-allowed !important;
  filter:grayscale(1) !important;
  box-shadow:none !important;
}
.pd-driver-application button.pd-approval-blocked:disabled:focus-visible {
  outline:3px solid #e3c16e !important;
  outline-offset:2px;
}
.pd-driver-application .pda-stage2-hint { color:#e8c47c; font-size:14px; line-height:1.45; }
.pd-driver-application .pd-approval-blocked-reason { color:#c5c5c5; font-size:13px; line-height:1.4; margin:6px 0 12px; }
</style>
"""
OLD="""if(target==='approved'&&b.disabled){b.title=pdStage2ApprovalHint(a,missingPhotos)||pdL('Проверка пока недоступна');b.setAttribute('aria-label',pdL('Одобрить')+': '+b.title)}"""
NEW="""if(target==='approved'&&b.disabled){
      b.classList.add('pd-approval-blocked');
      b.title=pdStage2ApprovalHint(a,missingPhotos)||pdL('Проверка пока недоступна');
      b.setAttribute('aria-label',pdL('Одобрить')+': '+b.title);
      b.setAttribute('aria-disabled','true');
      const why=document.createElement('p');
      why.className='pd-approval-blocked-reason';
      why.textContent=b.title;
      actions.append(why);
    }"""
# NOTE: reason is appended inside actions before button; valid inline panel.
def check(cond,name):
 if not cond:raise RuntimeError("BLOCK_"+name)
 print("PASS",name,flush=True)
def exact(source,old,new,label):
 check(source.count(old)==1,"UNIQUE_"+label)
 return source.replace(old,new,1)
def change(source):
 check(hashlib.sha256(source.encode()).hexdigest()==SOURCE_SHA,"EXACT_ACTIVE_HTML_SHA")
 check("pd-pilot-cockpit-adapter-stage-js" in source,"EXISTING_COCKPIT_PRESERVED")
 check("function pdStage2ApprovalHint(a,missingPhotos)" in source,"EXISTING_APPROVAL_HINT_PRESERVED")
 check("b.disabled=a.status===target||(target==='approved'&&(missingPhotos.length>0||a.status==='stage2'));" in source,"BUTTON_STATE_PRESERVED")
 source=exact(source,"</head>",STYLE+"</head>","HEAD_ANCHOR")
 source=exact(source,OLD,NEW,"APPROVAL_DISABLED_VISUAL")
 check(source.count("pd-stage2-approval-disabled-visual")==1,"STYLE_INJECTED_ONCE")
 check(source.count("pd-approval-blocked-reason")==2,"REASON_CLASS_USED_IN_CSS_AND_JS")
 check(source.count("function pdLoadDriverApplications(){")==1,"APPLICATION_LOADER_PRESERVED")
 check(source.count('id="pdbPays"')==1,"PASSENGER_CHECKOUT_PRESERVED")
 check(source.count("/assets/pd-admin-console-v4.js")>=1,"ORDER_DISPATCHER_PRESERVED")
 return source
def get(name):
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 req=urllib.request.Request(BASE+name,headers={"Authorization":"Token "+token},method="GET")
 with urllib.request.urlopen(req,timeout=40) as response:
  data=response.read(700000)
  check(response.status==200,"GET_"+name.replace("/","_"))
 return data.decode("utf8")
class JS(HTMLParser):
 def __init__(self):
  super().__init__();self.active=False;self.parts=[]
 def handle_starttag(self,tag,attrs):
  if tag=="script" and "src" not in dict(attrs):
   self.parts.append("");self.active=True
 def handle_data(self,value):
  if self.active:self.parts[-1]+=value
 def handle_endtag(self,tag):
  if tag=="script":self.active=False
def main():
 html=get(HTML);backend=get(BACKEND)
 check(hashlib.sha256(backend.encode()).hexdigest()==BACKEND_SHA,"SERVER_CODE_UNCHANGED_SHA")
 for s in ("if target=='approved' and r['status']!='approved':",
           "if r['stage']==1:target='stage2'",
           "if r['status']=='stage2' and target=='approved':",
           "raise ValueError('Дождитесь заполнения второго этапа водителем')",
           "if set(required)-stored:"):
  check(s in backend,"SERVER_APPROVAL_GATE_"+str(len(s)))
 out=change(html)
 with tempfile.TemporaryDirectory(prefix="pd-stage2-button-") as d:
  p=pathlib.Path(d)/"index.html";p.write_text(out,encoding="utf8")
  check(p.read_text(encoding="utf8")==out,"CANDIDATE_BYTE_ROUNDTRIP")
  parser=JS();parser.feed(out)
  modified=[x for x in parser.parts if "pd-approval-blocked-reason" in x]
  check(len(modified)==1,"ONE_CHANGED_JS_BLOCK")
  path=pathlib.Path(d)/"modified.js";path.write_text(modified[0],encoding="utf8")
  n=subprocess.run(["node","--check",str(path)],text=True,capture_output=True)
  if n.returncode:raise RuntimeError("CHANGED_JS_SYNTAX_"+n.stderr[-180:])
  check(True,"CHANGED_JS_SYNTAX")
  # Exercise exact extracted button handler expression on synthetic mock DOM
  start=modified[0].find("const actions=document.createElement('div');actions.className='actions';for(const[target,label]")
  check(start>=0,"ACTUAL_BUTTON_HANDLER_LOCATED")
  block=modified[0][start:modified[0].find("row.append(actions);area.append(row)",start)]
  js=(r"""
const assert=require('assert');
const api=()=>{throw Error('NETWORK_NOT_ALLOWED')};
const pdL=x=>x;
const pdStage2ApprovalHint=(a,missingPhotos)=>a.status==='stage2'?'Ожидается отправка второго этапа':missingPhotos.length?'Нет документов':'';
const document={createElement:tag=>({tag,disabled:false,className:'',attrs:{},children:[],classList:{values:[],add(x){this.values.push(x)}},setAttribute(k,v){this.attrs[k]=v},append(...x){this.children.push(...x)},set title(x){this._title=x},get title(){return this._title}})};
async function runState(status,stage,missingPhotos){
 const a={status,stage,telegram_id:1234},row=document.createElement('article'),area=document.createElement('div');
 // block is source fragment from actual production
 """+block+r"""
 row.append(actions);area.append(row);
 const btns=actions.children.filter(x=>x.tag==='button');
 const approve=btns[0];
 return {approve,reason:actions.children.find(x=>x.className==='pd-approval-blocked-reason')};
}
(async()=>{
 let x=await runState('stage2',1,[]);
 assert.strictEqual(x.approve.disabled,true);
 assert(x.approve.classList.values.includes('pd-approval-blocked'));
 assert(x.reason.textContent.includes('второго этапа'));
 assert.strictEqual(x.approve.attrs['aria-disabled'],'true');
 console.log('PASS STAGE2_BUTTON_DISABLED_GREY_CLASS_REASON');
 x=await runState('pending',2,['insurance']);
 assert.strictEqual(x.approve.disabled,true);
 assert(x.reason.textContent.includes('Нет документов'));
 console.log('PASS PENDING_MISSING_DOCS_BLOCKED');
 x=await runState('pending',2,[]);
 assert.strictEqual(x.approve.disabled,false);
 assert.strictEqual(x.reason,undefined);
 console.log('PASS PENDING_ALL_DOCS_APPROVAL_AVAILABLE');
 console.log('PASS SYNTHETIC_STATUS_TESTS_NO_API_REQUESTS');
})().catch(e=>{console.error(e);process.exit(1)});
 """)
  # Definition of btn from current source is simple; only verify disabled + class.
  js=js.replace("const pdL=x=>x;", "const pdL=x=>x;const btn=undefined;")
  t=pathlib.Path(d)/"synthetic.cjs";t.write_text(js,encoding="utf8")
  result=subprocess.run(["node",str(t)],capture_output=True,text=True)
  if result.returncode:raise RuntimeError("HANDLER_TEST_FAILED "+result.stderr[-1200:])
  print(result.stdout.strip(),flush=True)
 print("CANDIDATE_SHA256",hashlib.sha256(out.encode()).hexdigest(),flush=True)
 print("STAGE2_BUTTON_VISUAL_DRYRUN_PASS",flush=True)
 print("NO_PRODUCTION_WRITES_NO_ORDERS_NO_USERS_NO_PAYMENTS",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print("STAGE2_BUTTON_VISUAL_BLOCKED",type(exc).__name__,str(exc)[:220],flush=True)
  raise SystemExit(1)
