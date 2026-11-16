"""PR27 guarded deploy fault injection. Only synthetic memory; no API calls."""
import contextlib,hashlib,importlib.util,io,os,pathlib,sys,urllib.error
from unittest.mock import patch
path=pathlib.Path(__file__).resolve().parents[1]/"ops/pr27_guarded_install_NOT_EXECUTED.py"
spec=importlib.util.spec_from_file_location("pilot_guarded_release",path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SRC=m.LIVE+m.HTML
OLD=b"<html><head></head><body>pdPilotWork</body></html>"
NEW=b"<html><head></head><body>pdPilotWork pd-pilot-cockpit-adapter-stage-js</body></html>"
class Fake:
 def __init__(self,stage):
  self.files={SRC:OLD}
  self.stage=stage
  self.once=True
  self.health_calls=0
  self.reloads=0
 def read(self,path,token):
  if path not in self.files:raise urllib.error.HTTPError(path,404,'Not found',{},None)
  return self.files[path]
 def upload(self,path,data,token):
  if path==SRC and self.once and self.stage=="partial":
   self.once=False
   self.files[path]=data[:11]
   raise IOError("SIMULATED_PARTIAL_WRITE")
  self.files[path]=data
  assert self.files[path]==data
 def api(self,url,token,method="GET",body=None,ctype=None):
  assert url.endswith("/files/path"+m.BACKUP)
  return 200,b"[]"
 def reload(self,token):self.reloads+=1
 def check(self,marker):
  self.health_calls+=1
  if self.stage=="post_health" and self.health_calls==2:return False
  return True
def run_case(stage):
 fake=Fake(stage);log=io.StringIO()
 with (patch.object(m,"read",side_effect=fake.read),
       patch.object(m,"upload",side_effect=fake.upload),
       patch.object(m,"api",side_effect=fake.api),
       patch.object(m,"reload",side_effect=fake.reload),
       patch.object(m,"check_public",side_effect=fake.check),
       patch.object(m,"overlay",return_value=NEW.decode()),
       patch.object(m,"PINNED",hashlib.sha256(OLD).hexdigest()),
       patch.dict(os.environ,{"OPERATOR_APPROVED_PR27":"YES","PYTHONANYWHERE_API_TOKEN":"FAKE"}),
       patch.object(sys,"argv",["pr27_guarded_install_NOT_EXECUTED.py","--execute"]),
       contextlib.redirect_stdout(log)):
  try:m.main()
  except (RuntimeError,IOError):pass
  else:raise AssertionError("INJECTED_FAILURE_NOT_TRIGGERED")
 assert fake.files[SRC]==OLD
 assert fake.reloads>=1
 assert "PR27_ROLLBACK_VERIFIED" in log.getvalue()
 assert len(fake.files)==3
 print("PASS",stage.upper(),"FULL_BYTE_RECOVERY_AND_RELOAD",flush=True)
run_case("partial")
run_case("post_health")
with patch.dict(os.environ,{"OPERATOR_APPROVED_PR27":""}),patch.object(sys,"argv",["pr27_guarded_install_NOT_EXECUTED.py","--execute"]):
 try:m.main()
 except RuntimeError as e:assert "OPERATOR_APPROVAL_REQUIRED" in str(e)
 else:raise AssertionError("NO_APPROVAL_WAS_ACCEPTED")
print("PASS DEPLOY_WITHOUT_APPROVAL_BLOCKED")
print("PR27_GUARDED_ROLLBACK_TESTS_PASSED")
print("NO_PRODUCTION_WRITES_OR_PAYMENTS")
