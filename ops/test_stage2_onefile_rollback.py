"""Synthetic fault injection for stage2 one-file release. No production token/network."""
import hashlib,importlib.util,io,os,pathlib,sys,contextlib,urllib.error
from unittest.mock import patch
path=pathlib.Path(__file__).resolve().parents[1]/"ops/stage2_onefile_guarded_release.py"
spec=importlib.util.spec_from_file_location("stage2_release",path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
OLD=b"<html><body>pd-pilot-cockpit-adapter-stage-js</body></html>"
NEW=b"<html><body>pd-pilot-cockpit-adapter-stage-js function pdStage2ApprovalHint(a,missingPhotos)</body></html>"
class Fake:
 def __init__(self,fail):
  self.files={m.LIVE:OLD};self.fail=fail;self.once=True;self.reloads=0
 def get(self,path,token):
  if path not in self.files:raise urllib.error.HTTPError(path,404,"Missing",{},None)
  return self.files[path]
 def put(self,path,data,token):
  if path==m.LIVE and self.fail=="partial" and self.once:
   self.once=False;self.files[path]=data[:6];raise IOError("partial write")
  self.files[path]=data
  assert self.get(path,token)==data
 def call(self,url,token,method="GET",data=None,ctype=None):
  assert url.endswith("/private_drive_backups/");return 200,b""
 def reload(self,token):self.reloads+=1
 def public(self,marker):
  if marker==b"function pdStage2ApprovalHint(a,missingPhotos)" and self.fail=="health":return False
  return True
for fail in ("partial","health"):
 fake=Fake(fail);out=io.StringIO()
 with patch.object(m,"EXPECTED",hashlib.sha256(OLD).hexdigest()),patch.object(m,"CANDIDATE_SHA",hashlib.sha256(NEW).hexdigest()),patch.object(m,"patch",return_value=NEW.decode()),patch.object(m,"get",side_effect=fake.get),patch.object(m,"put",side_effect=fake.put),patch.object(m,"call",side_effect=fake.call),patch.object(m,"reload",side_effect=fake.reload),patch.object(m,"public",side_effect=fake.public),patch.dict(os.environ,{"PD_APPROVED_STAGE2_UI":"YES","PYTHONANYWHERE_API_TOKEN":"SYNTHETIC"}),patch.object(sys,"argv",["release","--execute"]),contextlib.redirect_stdout(out):
  try:m.main()
  except (IOError,RuntimeError):pass
  else:raise AssertionError("injected failure was ignored")
 assert fake.files[m.LIVE]==OLD
 assert fake.reloads>=1
 assert "STAGE2_ROLLBACK_VERIFIED" in out.getvalue()
 assert len(fake.files)==3
 print("PASS",fail.upper(),"RESTORE_AND_RELOAD")
with patch.dict(os.environ,{"PD_APPROVED_STAGE2_UI":""}),patch.object(sys,"argv",["release","--execute"]):
 try:m.main()
 except RuntimeError as exc:assert "OPERATOR_APPROVAL_REQUIRED" in str(exc)
 else:raise AssertionError("no approval accepted")
print("PASS EXPLICIT_RELEASE_PERMISSION_GUARD")
print("STAGE2_ROLLBACK_TESTS_PASS")
print("NO_REMOTE_CALLS_NO_RECORD_MUTATIONS")
