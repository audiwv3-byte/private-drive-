"""Fault-injection release validation, no network or real application state."""
import contextlib,hashlib,importlib.util,io,os,pathlib,sys,urllib.error
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ops import stage2_button_visual_guarded_release as m
OLD=b"<html><head></head><body>function pdStage2ApprovalHint(a,missingPhotos)</body></html>"
NEW=OLD.replace(b"</head>",b"<style>pd-stage2-approval-disabled-visual</style></head>").replace(b"</body>",b"pd-approval-blocked-reason</body>")
class Fake:
 def __init__(self,mode):
  self.mode=mode;self.files={m.LIVE:OLD,m.BACKEND:b"synthetic backend"};self.loads=0;self.trigger=True
 def get(self,path,token):
  if path not in self.files:raise urllib.error.HTTPError(path,404,"",{},None)
  return self.files[path]
 def put(self,path,data,token):
  if path==m.LIVE and self.mode=="partial" and self.trigger:
   self.trigger=False;self.files[path]=data[:8];raise IOError("partial")
  self.files[path]=data;assert self.files[path]==data
 def call(self,url,token,method="GET",data=None,ctype=None):
  assert method=="GET";return 200,b""
 def reload(self,token):self.loads+=1
 def public(self,marker):
  if self.mode=="health" and marker==b"pd-stage2-approval-disabled-visual":return False
  return True
for mode in ("partial","health"):
 f=Fake(mode);out=io.StringIO()
 with patch.object(m,"SOURCE_SHA",hashlib.sha256(OLD).hexdigest()),patch.object(m,"BACKEND_SHA",hashlib.sha256(b"synthetic backend").hexdigest()),patch.object(m,"TARGET_SHA",hashlib.sha256(NEW).hexdigest()),patch.object(m,"change",return_value=NEW.decode()),patch.object(m.base,"get",side_effect=f.get),patch.object(m.base,"put",side_effect=f.put),patch.object(m.base,"call",side_effect=f.call),patch.object(m.base,"reload",side_effect=f.reload),patch.object(m.base,"public",side_effect=f.public),patch.dict(os.environ,{"PD_APPROVED_STAGE2_VISUAL":"YES","PYTHONANYWHERE_API_TOKEN":"FAKE"}),patch.object(sys,"argv",["release","--execute"]),contextlib.redirect_stdout(out):
  try:m.main()
  except (RuntimeError,IOError):pass
  else:raise AssertionError("expected failure")
 assert f.files[m.LIVE]==OLD,mode
 assert f.loads>=1,mode
 assert "STAGE2_VISUAL_ROLLBACK_VERIFIED" in out.getvalue(),out.getvalue()
 assert len(f.files)==4
 print("PASS",mode.upper(),"RESTORES_ORIGINAL_AND_RELOADS",flush=True)
with patch.dict(os.environ,{"PD_APPROVED_STAGE2_VISUAL":""}),patch.object(sys,"argv",["release","--execute"]):
 try:m.main()
 except RuntimeError as e:assert "OPERATOR_APPROVAL_REQUIRED" in str(e)
 else:raise AssertionError("unapproved deployment permitted")
print("PASS EXPLICIT_APPROVAL_GUARD")
print("STAGE2_VISUAL_ROLLBACK_SYNTHETIC_PASS")
