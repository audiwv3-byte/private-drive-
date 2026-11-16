"""Offline PR28 deploy failover regression; no PythonAnywhere network calls.
Tests prewrite blockers, partial write, web health failure, restoration of 3 files.
"""
import contextlib,hashlib,importlib.util,io,os,pathlib,sys,tempfile
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
path=ROOT/"ops/pr28_guarded_deploy_NOT_EXECUTED.py"
spec=importlib.util.spec_from_file_location("pr28_offline_deploy",path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ORIGINAL={name:("ORIGINAL_"+name).encode() for name in m.FILES}
NEW={name:("CANDIDATE_"+name).encode() for name in m.FILES}
HASH={name:hashlib.sha256(raw).hexdigest() for name,raw in ORIGINAL.items()}
def check(ok,label):
    if not ok:raise AssertionError(label)
    print("PASS",label,flush=True)
class Backend:
    def __init__(self,fail):
        self.files={m.ROOT+name:raw for name,raw in ORIGINAL.items()}
        self.fail=fail
        self.fail_once=True
        self.reloads=0
        self.restarts=0
        self.writes=[]
    def read(self,path,token):
        if path not in self.files:raise FileNotFoundError(path)
        return self.files[path]
    def put(self,path,data,token):
        self.writes.append(path)
        if self.fail=="second_partial" and self.fail_once and path==m.ROOT+m.FILES[1]:
            self.fail_once=False
            self.files[path]=data[:7]
            raise IOError("SYNTHETIC_PARTIAL_SECOND")
        self.files[path]=data
        if self.files[path]!=data:raise IOError("MOCK_UPLOAD_READBACK_FAILED")
    def web_reload(self,token):self.reloads+=1
    def bot_restart(self,token,id):
        check(id==777,"BOT_TASK_KNOWN")
        self.restarts+=1
    def health(self):return self.fail!="health_failure"
def run_case(fail):
    obj=Backend(fail)
    saved=io.StringIO()
    with patch.object(m,"PINNED",HASH),patch.object(m,"bot_task",return_value=777),patch.object(m,"read",side_effect=obj.read),patch.object(m,"put",side_effect=obj.put),patch.object(m,"reload_web",side_effect=obj.web_reload),patch.object(m,"restart_bot",side_effect=obj.bot_restart),patch.object(m,"smoke",side_effect=obj.health),patch.object(m,"build",return_value=NEW),patch.dict(os.environ,{"OPERATOR_APPROVED_PR28":"YES","PYTHONANYWHERE_API_TOKEN":"SYNTHETIC_TOKEN"}),patch.object(sys,"argv",["pr28_guarded_deploy_NOT_EXECUTED.py","--execute"]),contextlib.redirect_stdout(saved):
        try:m.main()
        except (IOError,RuntimeError):pass
        else:raise AssertionError("SIMULATED_FAILURE_MISSED")
    check(all(obj.files[m.ROOT+name]==ORIGINAL[name] for name in m.FILES),"RESTORE_ALL_THREE_FILES_"+fail)
    check(obj.reloads>=1 and obj.restarts>=1,"WEB_AND_BOT_RESTART_ROLLBACK_"+fail)
    check("ROLLBACK_VERIFIED" in saved.getvalue(),"ROLLBACK_BYTES_VERIFIED_"+fail)
    check(len([p for p in obj.files if "/private_drive_backups/" in p])==6,
          "SIX_BACKUP_SOURCE_AND_CANDIDATE_FILES_"+fail)
run_case("second_partial")
run_case("health_failure")
# Unavailable bot restart control must prevent any production or backup writing.
obj=Backend("no_bot")
with patch.object(m,"bot_task",side_effect=RuntimeError("BOT_RESTART_CONTROL_NOT_VERIFIED")),patch.object(m,"read",side_effect=AssertionError("SOURCE_READ_SHOULD_NOT_START")),patch.object(m,"put",side_effect=AssertionError("NO_WRITES_ALLOWED")),patch.dict(os.environ,{"OPERATOR_APPROVED_PR28":"YES","PYTHONANYWHERE_API_TOKEN":"FAKE"}),patch.object(sys,"argv",["pr28_guarded_deploy_NOT_EXECUTED.py","--execute"]):
    try:m.main()
    except RuntimeError as e:check("BOT_RESTART_CONTROL_NOT_VERIFIED" in str(e),"UNKNOWN_BOT_RUNTIME_FAIL_CLOSED")
    else:raise AssertionError("UNVERIFIED_BOT_RUNTIME_ALLOWED")
with patch.object(m,"bot_task",side_effect=AssertionError("BOT_CHECK_SHOULD_NOT_START")),patch.dict(os.environ,{"OPERATOR_APPROVED_PR28":""}),patch.object(sys,"argv",["pr28_guarded_deploy_NOT_EXECUTED.py","--execute"]):
    try:m.main()
    except RuntimeError as e:check("OPERATOR_APPROVAL_REQUIRED" in str(e),"NO_APPROVAL_BLOCKS_ALL_WRITES")
    else:raise AssertionError("UNAPPROVED_DEPLOY_ALLOWED")
print("PR28_DEPLOY_OFFLINE_ROLLBACK_AND_BLOCKER_TESTS_PASSED",flush=True)
print("NO_PYTHONANYWHERE_REQUESTS_NO_PAYMENTS_NO_ORDERS",flush=True)
