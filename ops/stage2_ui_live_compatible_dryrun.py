"""Stage2 UI-only production-compatible offline patch.
GET production HTML, construct candidate only in temporary runner. No writes.
"""
import hashlib,os,pathlib,re,subprocess,tempfile,urllib.request
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
EXPECTED="3e993f4d9bd957d8c02e5e364d4c65036b99ee2d17cc21ac8d1dbb6d859b1425"
PATH="miniapp/templates/index.html"
FUNCTION="""function pdStage2ApprovalHint(a,missingPhotos){
 const tr=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
 if(a.status==='stage2')return tr(
  'Первый этап подтверждён. Пилот должен открыть PRIVATE DRIVE, заполнить второй этап и отправить документы. До этого окончательное одобрение недоступно.',
  'Step 1 approved. Pilot must open PRIVATE DRIVE, complete step 2 and submit documents before final approval.',
  '1 etapas patvirtintas. Pilotas turi užpildyti 2 etapą ir pateikti dokumentus. Iki tol galutinis patvirtinimas negalimas.');
 if(missingPhotos.length)return tr(
  'Одобрение заблокировано: отсутствуют обязательные документы. Пилот должен загрузить недостающие файлы.',
  'Approval blocked: mandatory documents are missing. Ask the pilot to upload the missing files.',
  'Patvirtinimas negalimas: trūksta privalomų dokumentų. Pilotas turi įkelti trūkstamus failus.');
 if(a.status==='pending'&&a.stage===2)return tr(
  'Документы второго этапа отправлены. Диспетчер может завершить проверку и одобрить пилота.',
  'Step 2 documents submitted. Dispatcher can complete verification and approve the pilot.',
  '2 etapo dokumentai pateikti. Dispečeris gali užbaigti patikrą ir patvirtinti pilotą.');
 if(a.status==='pending'&&a.stage===1)return tr(
  'Этап 1: после одобрения пилоту откроется второй этап. Это ещё не доступ к заказам.',
  'Step 1: approval unlocks step 2; it does not grant trip access.',
  '1 etapas: patvirtinimas atvers 2 etapą, tačiau kelionių prieigos dar nesuteiks.');
 return '';
}
"""
def exact(src,old,new,name):
 n=src.count(old)
 if n!=1:raise RuntimeError(f"UNSAFE_{name}_HITS_{n}")
 return src.replace(old,new,1)
def patch(src):
 if hashlib.sha256(src.encode()).hexdigest()!=EXPECTED:raise RuntimeError("LIVE_HTML_SHA_CHANGED_ABORT")
 old="async function pdLoadDriverApplications(){"
 src=exact(src,old,FUNCTION+"\n"+old,"HELPER")
 old="pdAppendDocumentButtons(row,a);"
 new="""pdAppendDocumentButtons(row,a);
   const hint=pdStage2ApprovalHint(a,missingPhotos);
   if(hint){const explanation=document.createElement('p');explanation.className='pda-stage2-hint';
     explanation.setAttribute('role','status');explanation.textContent=hint;row.append(explanation)}"""
 src=exact(src,old,new,"EXPLANATION")
 old="b.disabled=a.status===target||(target==='approved'&&(missingPhotos.length>0||a.status==='stage2'));b.onclick="
 new="""b.disabled=a.status===target||(target==='approved'&&(missingPhotos.length>0||a.status==='stage2'));
    if(target==='approved'&&b.disabled){b.title=pdStage2ApprovalHint(a,missingPhotos)||pdL('Проверка пока недоступна');b.setAttribute('aria-label',pdL('Одобрить')+': '+b.title)}
    b.onclick="""
 src=exact(src,old,new,"BUTTON_TITLE")
 assert 'pdStage2ApprovalHint(a,missingPhotos)' in src
 assert src.count("function pdLoadDriverApplications(){")==1
 assert src.count("data-method=\"Наличными\"")==1  # Preserve unrelated passenger UI exactly
 assert src.count("pd-pilot-cockpit-adapter-stage-js")==1 # Keep installed GPS
 return src
def main():
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 req=urllib.request.Request(BASE+PATH,method="GET",headers={"Authorization":"Token "+token})
 with urllib.request.urlopen(req,timeout=40) as r:source=r.read(700000).decode("utf8")
 candidate=patch(source)
 print("PASS LIVE_HTML_PIN",hashlib.sha256(source.encode()).hexdigest(),flush=True)
 print("PASS STAGE2_ONLY_PATCH",hashlib.sha256(candidate.encode()).hexdigest(),flush=True)
 print("NO_PRODUCTION_WRITES_NO_ORDERS_NO_PERSONAL_DATA",flush=True)
 with tempfile.TemporaryDirectory(prefix="pd-stage2-ui-") as tmp:
  p=pathlib.Path(tmp)/"candidate.html";p.write_text(candidate,encoding="utf8")
  assert p.read_text(encoding="utf8")==candidate
  from html.parser import HTMLParser
  class Extract(HTMLParser):
   def __init__(self):super().__init__();self.n=0;self.parts=[];self.capture=False
   def handle_starttag(self,tag,attrs):
    if tag=="script" and not dict(attrs).get("src"):
     self.capture=True;self.n+=1;self.parts.append("")
   def handle_endtag(self,tag):
    if tag=="script":self.capture=False
   def handle_data(self,text):
    if self.capture:self.parts[-1]+=text
  parser=Extract();parser.feed(candidate)
  touched=[(i,body) for i,body in enumerate(parser.parts) if "function pdStage2ApprovalHint(a,missingPhotos)" in body]
  assert len(touched)==1,"Exactly one existing inline script should receive the stage2 hint"
  for i,body in touched:
   f=pathlib.Path(tmp)/f"modified_inline_{i}.js";f.write_text(body,encoding="utf8")
   result=subprocess.run(["node","--check",str(f)],capture_output=True,text=True)
   if result.returncode:
    print("MODIFIED_INLINE_PARSE_ERROR",result.stderr[-1200:],flush=True)
    raise RuntimeError("MODIFIED_INLINE_SCRIPT_SYNTAX_INVALID")
  print("PASS MODIFIED_EMBEDDED_JS_SYNTAX",len(touched),flush=True)
  # Execute only the pure explanation helper on synthetic records.
  helper=FUNCTION+"""
  const assert=require('assert');
  const a=({status,stage},missing)=>pdStage2ApprovalHint({status,stage},missing);
  const step2=a({status:'stage2',stage:1},[]);
  assert(step2.includes('Пилот должен')&&step2.includes('второй этап'));
  assert(a({status:'pending',stage:2},['insurance']).includes('заблокировано'));
  assert(a({status:'pending',stage:2},[]).includes('может завершить'));
  assert(a({status:'pending',stage:1},[]).includes('ещё не доступ'));
  assert(a({status:'approved',stage:2},[])==='');
  console.log('PASS STAGE2_HINT_SYNTHETIC_STATES');
  """
  test=pathlib.Path(tmp)/"hint.cjs";test.write_text("global.window={PD_LANG:'ru'};"+helper,encoding="utf8")
  r=subprocess.run(["node",str(test)],capture_output=True,text=True,check=True)
  print(r.stdout.strip(),flush=True)
 print("STAGE2_UI_LIVE_COMPATIBLE_OFFLINE_PASS",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("STAGE2_UI_OFFLINE_BLOCKED",type(e).__name__,str(e)[:140],flush=True)
  raise SystemExit(1)
