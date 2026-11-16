"""Issue #30 candidate regression run, synthetic SQLite/Flask/Node only.

No real pilot ID, no live POST; candidate sources are GET from PythonAnywhere
and written to a temporary GitHub runner directory only.
"""
import ast,hashlib,importlib.util,io,os,pathlib,re,sqlite3,subprocess,sys,tempfile,types
from datetime import datetime,timezone
from html.parser import HTMLParser
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import pd_document_review as reviews
from flask import Flask,jsonify
from ops.issue30_build_live_candidates import main as build

def check(pred,label):
 if not pred:raise AssertionError(label)
 print("PASS",label,flush=True)

class Scripts(HTMLParser):
 def __init__(self):super().__init__();self.current=None;self.scripts=[]
 def handle_starttag(self,tag,attrs):
  if tag=="script" and not dict(attrs).get("src"):
   self.current=[];self.scripts.append(self.current)
 def handle_endtag(self,tag):
  if tag=="script":self.current=None
 def handle_data(self,data):
  if self.current is not None:self.current.append(data)

class Core:
 USERS_DB="synthetic"
 def __init__(self,sqlite_path):self.path=str(sqlite_path)
 def db(self,unused):
  c=sqlite3.connect(self.path)
  c.row_factory=sqlite3.Row
  return c
 def is_admin(self,uid):return uid==9001
 def now(self):return datetime(2026,11,17,tzinfo=timezone.utc)
 def initialize(self):pass
 def clean_phone(self,p):return p
 def notify_admins(self,p):pass

def node_inline(html,tmp):
 parser=Scripts();parser.feed(html)
 modified=["".join(lines) for lines in parser.scripts if "function pdReviewDocumentsControl(row,a)" in "".join(lines)]
 check(len(modified)==1,"ONE_ADMIN_SCRIPT_MODIFIED")
 js=pathlib.Path(tmp)/"admin.js";js.write_text(modified[0],encoding="utf8")
 p=subprocess.run(["node","--check",str(js)],capture_output=True,text=True)
 if p.returncode:raise RuntimeError("MODIFIED_JS_PARSE_ERROR "+p.stderr[-700:])
 check(True,"MODIFIED_JS_SYNTAX_VALID")
 # Isolate exactly the pure UI final-approval permission function.
 m=re.search(r"function pdReviewRequiredSides\(a\)\{.*?\}\s*function pdReviewAllApproved\(a,items\)\{.*?\}",modified[0],re.S)
 check(m is not None,"UI_FINAL_APPROVAL_PREDICATE_FOUND")
 js2=pathlib.Path(tmp)/"ui-gate.cjs"
 js2.write_text("""const assert=require('node:assert/strict');
"""+m.group(0)+"""
const s=['license_front','license_back','car_front','car_rear','car_interior'];
let r={};for(const x of s)r[x]={status:'approved'};
assert(pdReviewAllApproved({status:'pending',stage:1},r));
assert(!pdReviewAllApproved({status:'stage2',stage:1},r));
assert(!pdReviewAllApproved({status:'pending',stage:2},r));
r.insurance={status:'rejected'};
assert(!pdReviewAllApproved({status:'pending',stage:2},r));
for(const x of ['registration_front','ltsa','activity','insurance','portrait'])r[x]={status:'approved'};
assert(pdReviewAllApproved({status:'pending',stage:2},r));
console.log('PASS UI_APPROVAL_GATE_SYNTHETIC_STATES');
""",encoding="utf8")
 run=subprocess.run(["node",str(js2)],capture_output=True,text=True)
 if run.returncode:raise RuntimeError("UI_GATE_SYNTHETIC_FAIL "+run.stderr[-1000:])
 print(run.stdout.strip(),flush=True)

def synthetic_flask(source,tmp):
 # Do not import production app/config. Stub only unavailable photo plugin and
 # language module for isolated import of the exact candidate onboarding code.
 heif=types.ModuleType("pillow_heif");heif.register_heif_opener=lambda:None
 lang=types.ModuleType("pd_languages");lang.language=lambda:"ru"
 lang.response_for=lambda x,y:x
 with patch.dict(sys.modules,{"pillow_heif":heif,"pd_languages":lang}):
  name="issue30_candidate_onboarding"
  spec=importlib.util.spec_from_file_location(name,str(source))
  module=importlib.util.module_from_spec(spec);sys.modules[name]=module
  spec.loader.exec_module(module)
  app=Flask("issue30_synthetic_app")
  app.config["TESTING"]=True
  context={"id":9001}
  core=Core(pathlib.Path(tmp)/"synthetic.sqlite3")
  @app.get("/api/me")
  def me():return jsonify(id=context["id"],registered=True)
  module.register(app,core,lambda:(context["id"],{}))
  with core.db(core.USERS_DB) as c:
   c.execute("""INSERT INTO pd_driver_applications
     (telegram_id,name,phone,city,vehicle,vehicle_year,plate,seats,status,created_at,updated_at,stage)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
     (101,"Synthetic Driver","+37060000000","","",1980,"",4,"pending","2026","2026",1))
   for side in reviews.FIRST+reviews.SECOND:
    c.execute("INSERT INTO pd_driver_documents VALUES (?,?,?,?)",
              (101,side,("fake image "+side).encode(),"2026"))
  with app.test_client() as client:
   resp=client.get("/api/admin/driver-applications/101/document-reviews")
   check(resp.status_code==200,"ADMIN_REVIEWS_ENDPOINT")
   check(resp.json["documents"]["license_front"]["status"]=="pending","LEGACY_PENDING_NOT_APPROVED")
   with core.db(core.USERS_DB) as c:
    s=reviews.states(c,101)
   # final approval must deny until each stage1 doc is approved
   try:
    client.post("/api/admin/driver-applications/101/decision",json={"status":"approved"})
   except reviews.ReviewError:pass
   else:raise AssertionError("stage1 approval bypass")
   check(True,"BACKEND_BLOCKS_STAGE1_WITHOUT_DOC_REVIEWS")
   for side in reviews.FIRST:
    res=client.post("/api/admin/driver-applications/101/document-reviews/"+side,
                    json={"status":"approved","sha256":s[side]["sha256"]})
    check(res.status_code==200,"ADMIN_APPROVES_"+side)
   decision=client.post("/api/admin/driver-applications/101/decision",json={"status":"approved"})
   check(decision.status_code==200,"STAGE1_APPROVAL_ACCEPTED")
   with core.db(core.USERS_DB) as c:
    row=c.execute("SELECT status,stage FROM pd_driver_applications WHERE telegram_id=101").fetchone()
    check((row["status"],row["stage"])==("stage2",1),"STAGE1_ADVANCES_TO_STAGE2_NOT_FULL_APPROVAL")
   # stage2 status must remain unapprovable until pilot submits stage2.
   try:client.post("/api/admin/driver-applications/101/decision",json={"status":"approved"})
   except ValueError:pass
   else:raise AssertionError("stage2 status bypass")
   check(True,"STAGE2_NOT_SUBMITTED_BLOCKED")
   # Simulate pilot submitting second stage only within test fixture.
   with core.db(core.USERS_DB) as c:
    c.execute("UPDATE pd_driver_applications SET status='pending',stage=2 WHERE telegram_id=101")
   try:client.post("/api/admin/driver-applications/101/decision",json={"status":"approved"})
   except reviews.ReviewError:pass
   else:raise AssertionError("stage2 unreviewed bypass")
   check(True,"PENDING_STAGE2_WITHOUT_ALL_REVIEWS_BLOCKED")
   with core.db(core.USERS_DB) as c:s=reviews.states(c,101)
   for side in reviews.SECOND:
    r=client.post("/api/admin/driver-applications/101/document-reviews/"+side,
                  json={"status":"approved","sha256":s[side]["sha256"]})
    check(r.status_code==200,"ADMIN_APPROVES_"+side)
   ok=client.post("/api/admin/driver-applications/101/decision",json={"status":"approved"})
   check(ok.status_code==200,"FINAL_STAGE2_APPROVAL_ACCEPTED")
   with core.db(core.USERS_DB) as c:
    row=c.execute("SELECT status FROM pd_driver_applications WHERE telegram_id=101").fetchone()
    check(row["status"]=="approved","FINAL_APPROVAL_SAVED_ON_SYNTHETIC_DB_ONLY")
    check(c.execute("SELECT COUNT(*) FROM pd_document_review_events").fetchone()[0]==10,
          "TEN_AUDITED_DOCUMENT_APPROVAL_EVENTS")
   context["id"]=555
   try:client.get("/api/admin/driver-applications/101/document-reviews")
   except PermissionError:pass
   else:raise AssertionError("pilot got dispatcher access")
   check(True,"PILOT_CANNOT_READ_ADMIN_REVIEW_API")
   try:client.post("/api/admin/driver-applications/101/document-reviews/portrait",
                    json={"status":"approved","sha256":"a"*64})
   except PermissionError:pass
   else:raise AssertionError("pilot posted dispatcher decision")
   check(True,"PILOT_CANNOT_APPROVE_OWN_DOCUMENT")
   context["id"]=101
   mine=client.get("/api/me")
   check(mine.status_code==200,"PILOT_OWN_APPLICATION_RESPONSE")
   check(mine.json["driver_application"]["document_reviews"]["portrait"]["status"]=="approved",
         "PILOT_CAN_VIEW_OWN_DOCUMENT_REVIEW_STATUS")
 print("ISSUE30_BACKEND_INTEGRATION_SYNTHETIC_PASS",flush=True)

def main():
 with tempfile.TemporaryDirectory(prefix="issue30-live-integration-") as p:
  build(p)
  p=pathlib.Path(p)
  backend=(p/"pd_onboarding.py").read_text()
  html=(p/"index.html").read_text()
  ast.parse(backend)
  check(True,"EXACT_LIVE_ONBOARDING_CANDIDATE_PYTHON_PARSE")
  node_inline(html,p)
  synthetic_flask(p/"pd_onboarding.py",p)
 print("ISSUE30_LIVE_INTEGRATION_DRYRUN_PASS",flush=True)
 print("NO_PYTHONANYWHERE_WRITES_NO_REAL_DATA_ACCESSED",flush=True)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("ISSUE30_LIVE_INTEGRATION_DRYRUN_BLOCKED",type(e).__name__,str(e)[:400],flush=True)
  raise SystemExit(1)
