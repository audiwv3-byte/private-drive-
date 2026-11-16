"""Issue #30 exact-live-source integration *candidate builder*, NO production writes.

Inputs are obtained by GET from PythonAnywhere. Creates candidates only in a
temporary local workspace. Exact SHA/anchor verification ensures no stale
GitHub-main file overwrites the active two-stage deployment.
"""
import hashlib,os,re,urllib.request,sys
from pathlib import Path
LIVE_URL="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
PINS={
 "pd_onboarding.py":"7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b",
 "miniapp/templates/index.html":"d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0",
 "miniapp_server.py":"f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4",
}
def sha(data):return hashlib.sha256(data).hexdigest()
def unique(src,old,new,label):
 n=src.count(old)
 if n!=1:raise RuntimeError(f"ANCHOR_{label}_MISMATCH_COUNT_{n}")
 return src.replace(old,new,1)
def get_live(path):
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 request=urllib.request.Request(LIVE_URL+path,headers={"Authorization":"Token "+token},method="GET")
 with urllib.request.urlopen(request,timeout=40) as res:
  if res.status!=200:raise RuntimeError("LIVE_GET_FAILED")
  data=res.read(800000)
 if sha(data)!=PINS[path]:raise RuntimeError("LIVE_SHA_MISMATCH_ABORT_"+path)
 print("PASS_SOURCE_SHA",path,sha(data),flush=True)
 return data.decode("utf8")
def patch_onboarding(src):
 src=unique(src,"import pd_languages\n","import pd_languages\nimport pd_document_review\n","REVIEW_IMPORT")
 src=unique(src,"    def document_sides(uid):",
 """    # New review tables only: existing BLOBs and driver statuses remain unchanged.
    with core.db(core.USERS_DB) as c:
        pd_document_review.ensure_tables(c)

    def document_sides(uid):""","SCHEMA_ON_STARTUP")
 src=unique(src,
  "        return dict(submitted=True,document_sides=document_sides(uid),**dict(row)) if row else None",
  """        if not row:return None
        with core.db(core.USERS_DB) as c:
            reviews=pd_document_review.states(c,uid)
        return dict(submitted=True,document_sides=document_sides(uid),
                    document_reviews=reviews,**dict(row))""","PILOT_OWN_REVIEW_STATES")
 src=unique(src,
  "        existing=own(uid)\n        stage=2 if existing",
  """        existing=own(uid)
        if existing and existing['status']=='approved':
            raise ValueError('Анкета одобрена. Изменение документов выполняет диспетчер')
        stage=2 if existing""","APPROVED_APPLICATION_IMMUTABILITY")
 src=unique(src,
  "            for side,image in photos.items():\n                c.execute('INSERT INTO pd_driver_documents",
  """            # Pilot may upload missing documents, or replace only a rejected one.
            reviews=pd_document_review.states(c,uid) if existing else {}
            for side in photos:
                if side in stored and reviews.get(side,{}).get('status')!='rejected':
                    raise ValueError('Сохранённые документы меняет диспетчер; отклонённый документ можно загрузить повторно')
            for side,image in photos.items():
                c.execute('INSERT INTO pd_driver_documents""","PILOT_DOCUMENT_REPLACEMENT_RIGHTS")
 src=unique(src,
  "                if r['stage']==1:target='stage2'",
  """                pd_document_review.require_approved_documents(c,applicant,int(r['stage']))
                if r['stage']==1:target='stage2'""","APPROVAL_GATE")
 src=unique(src,
  "    @app.get('/driver-privacy')",
  """    # Separate explicit document-by-document dispatcher decisions.
    pd_document_review.register(app,core,auth)

    @app.get('/driver-privacy')""","ADMIN_REVIEW_ROUTES")
 return src

UI_FUNC="""function pdReviewRequiredSides(a){
 return a.stage===1?
   ['license_front','license_back','car_front','car_rear','car_interior']:
   ['license_front','license_back','car_front','car_rear','car_interior',
    'registration_front','ltsa','activity','insurance','portrait'];
}
function pdReviewAllApproved(a,items){
 return a.status==='pending'&&pdReviewRequiredSides(a).every(s=>items?.[s]?.status==='approved');
}
function pdReviewDocumentsControl(row,a){
 const trigger=document.createElement('button');
 trigger.type='button';trigger.className='secondary';
 trigger.textContent=pdL('Проверить документы');
 const results=document.createElement('div');
 results.className='pd-document-review-panel';
 results.setAttribute('role','region');
 results.setAttribute('aria-label',pdL('Проверка документов пилота'));
 row.append(trigger,results);
 const base='/api/admin/driver-applications/'+Number(a.telegram_id)+'/document-reviews';
 const refresh=async()=>{
  results.replaceChildren();
  const data=await api(base);
  const documents=data.documents||{};
  const approve=row.querySelector('button[data-pd-final-approval]');
  const allApproved=pdReviewAllApproved(a,documents);
  if(approve){
   approve.disabled=!allApproved;
   approve.classList.toggle('pd-approval-blocked',!allApproved);
   approve.setAttribute('aria-disabled',String(!allApproved));
   const reason=approve.parentElement.querySelector('.pd-approval-blocked-reason');
   if(reason){reason.hidden=allApproved;reason.textContent=allApproved?'':pdL('Одобрите все обязательные документы перед подтверждением пилота')}
  }
  for(const side of [...new Set([...pdReviewRequiredSides(a),...(a.document_sides||[])])]){
   const entry=documents[side]||{status:'missing'};
   const line=document.createElement('div');
   line.className='pd-review-file-row';
   const label=document.createElement('strong');
   label.textContent=(pdDocumentLabels[side]||side)+' — '+pdL({
    missing:'Не загружен',pending:'На проверке',approved:'Одобрен',rejected:'Отклонён'
   }[entry.status]||entry.status);
   line.append(label);
   if(entry.status==='rejected'&&entry.reason){
    const note=document.createElement('p');note.textContent=entry.reason;line.append(note)
   }
   if(entry.status!=='missing'){
    const preview=document.createElement('button');
    preview.type='button';preview.className='secondary';preview.textContent=pdL('Просмотреть');
    preview.onclick=()=>pdPreviewDocument(side,Number(a.telegram_id));
    line.append(preview);
    for(const [status,text] of [['approved','Одобрить документ'],['rejected','Отклонить документ']]){
     const b=document.createElement('button');b.type='button';b.className='secondary';
     b.textContent=pdL(text);b.disabled=entry.status===status;
     b.onclick=async()=>{
      const reason=status==='rejected'?window.prompt(pdL('Причина отклонения (обязательно):')):'';
      if(reason===null)return;
      if(status==='rejected'&&(!reason||reason.trim().length<3)){message(pdL('Укажи причину отклонения'),true);return}
      try{
       await api(base+'/'+encodeURIComponent(side),{status,sha256:entry.sha256,reason});
       await refresh();
      }catch(error){message(pdL(error.message),true);await refresh()}
     };
     line.append(b);
    }
   }
   results.append(line)
  }
 };
 trigger.onclick=async()=>{
  trigger.disabled=true;try{await refresh()}catch(e){message(pdL(e.message),true)}
  finally{trigger.disabled=false}
 };
}
"""
def patch_ui(src):
 src=unique(src,"async function pdLoadDriverApplications(){",
  UI_FUNC+"\nasync function pdLoadDriverApplications(){","ADMIN_DOCUMENT_PANEL")
 src=unique(src,"pdAppendDocumentButtons(row,a);",
  "pdAppendDocumentButtons(row,a);pdReviewDocumentsControl(row,a);","ADMIN_PANEL_MOUNT")
 src=unique(src,
  "b.disabled=a.status===target||(target==='approved'&&(missingPhotos.length>0||a.status==='stage2'));",
  """b.disabled=a.status===target||(target==='approved'&&(missingPhotos.length>0||a.status==='stage2'));
    if(target==='approved'){b.dataset.pdFinalApproval='1';b.disabled=true}""",
  "DISABLE_FINAL_APPROVAL_UNTIL_REVIEW")
 old="function pdDocumentRefresh(){pdDriverStageRefresh();const saved=window.pdOnboardingUser?.driver_application?.document_sides||[];"
 new="""function pdDocumentRefresh(){pdDriverStageRefresh();const saved=window.pdOnboardingUser?.driver_application?.document_sides||[];const reviews=window.pdOnboardingUser?.driver_application?.document_reviews||{};"""
 src=unique(src,old,new,"PILOT_DOCUMENT_STATUS_CONTEXT")
 src=unique(src,
  "input.disabled=!pdActiveDocumentSides.includes(side);if(saved.includes(side)&&!pdDocumentFiles.has(side)){$('pdPhotoStatus_'+side).textContent=pdL('Фото уже загружено');",
  """input.disabled=!pdActiveDocumentSides.includes(side)||(saved.includes(side)&&reviews[side]?.status!=='rejected');if(saved.includes(side)&&!pdDocumentFiles.has(side)){$('pdPhotoStatus_'+side).textContent=pdL({
   pending:'На проверке',approved:'Одобрен',rejected:'Отклонён'
  }[reviews[side]?.status]||'Фото уже загружено')+(reviews[side]?.status==='rejected'&&reviews[side].reason?' — '+reviews[side].reason:'');""",
  "PILOT_UPLOAD_STATUS_AND_LOCK")
 css="""<style id="pd-issue30-document-review-dryrun">
.pd-driver-application .pd-document-review-panel{margin:10px 0;display:grid;gap:8px}
.pd-driver-application .pd-review-file-row{padding:10px;border:1px solid #60533d;border-radius:9px}
.pd-driver-application .pd-review-file-row>button{margin:5px}
.pd-driver-application button[data-pd-final-approval]:disabled{background:#515151!important;color:#fff!important;opacity:1!important;cursor:not-allowed!important}
</style>
"""
 src=unique(src,"</head>",css+"</head>","REVIEW_STYLE")
 return src
def main(destination):
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
 source={name:get_live(name) for name in PINS}
 backend=patch_onboarding(source["pd_onboarding.py"])
 html=patch_ui(source["miniapp/templates/index.html"])
 # Source is passed through untouched except exact targeted snippets.
 assert source["miniapp_server.py"].count("pd_onboarding.register(app, core, auth)")==1
 assert "pd-pilot-cockpit-adapter-stage-js" in html
 assert 'id="pdbPays"' in html
 assert html.count("function pdLoadDriverApplications(){")==1
 assert "pd_document_review.require_approved_documents" in backend
 assert backend.count("pd_document_review.register(app,core,auth)")==1
 (destination/"pd_onboarding.py").write_text(backend,encoding="utf8")
 (destination/"index.html").write_text(html,encoding="utf8")
 (destination/"miniapp_server.py").write_text(source["miniapp_server.py"],encoding="utf8")
 print("PASS_CANDIDATE_BUILT_ONLY_IN_TEMPORARY_RUNNER",flush=True)
 for name,data in (("pd_onboarding.py",backend),("index.html",html)):
  print("CANDIDATE_SHA256",name,sha(data.encode()),flush=True)
 print("NO_PRODUCTION_UPLOADS_NO_DB_READS_NO_PAYMENTS",flush=True)
if __name__=="__main__":
 if len(sys.argv)!=2:raise SystemExit("usage: issue30_build_live_candidates.py /tmp/candidates")
 main(sys.argv[1])
