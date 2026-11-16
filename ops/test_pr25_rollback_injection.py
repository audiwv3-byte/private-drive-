"""Failure-injection tests for PR25 deployment against a throwaway filesystem.

No PythonAnywhere network requests, production credentials, real orders or
payment provider calls. Import deployment module but patch its remote boundary.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"ops/pr25_guarded_deploy_NOT_EXECUTED.py"
spec=importlib.util.spec_from_file_location("pr25_deploy_unit",SCRIPT)
deploy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

ORIGINAL={
    "miniapp_server.py":b"SYNTHETIC_ORIGINAL_SERVER_001\n",
    "pd_trip_runtime_v4.py":b"SYNTHETIC_ORIGINAL_RUNTIME_002\n",
}
PATCHED={
    "miniapp_server.py":b"SYNTHETIC_PATCHED_SERVER_001\n",
    "pd_trip_runtime_v4.py":b"SYNTHETIC_PATCHED_RUNTIME_002\n",
}
assert all(ORIGINAL[name]!=PATCHED[name] for name in deploy.TARGETS)

class FakeRemote:
    def __init__(self,root,scenario):
        self.root=root
        self.scenario=scenario
        self.phase="before"
        self.reload_count=0
        self.live_attempts=0
        self.backups={}
        self.healthy_calls=0
        for name,data in ORIGINAL.items():
            filename=self.path(deploy.ROOT+"/"+name)
            filename.parent.mkdir(parents=True,exist_ok=True)
            filename.write_bytes(data)

    def path(self,remote):
        assert remote.startswith("/home/wilsonpark/")
        return self.root/remote.lstrip("/")

    def read(self,remote,token):
        return self.path(remote).read_bytes()

    def upload(self,remote,data,token):
        if "/private_drive_backups/" in remote:
            path=self.path(remote)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
            assert path.read_bytes()==data
            self.backups[remote]=data
            return
        assert remote.startswith(deploy.ROOT+"/"),"Unexpected live path"
        name=remote.split("/")[-1]
        self.live_attempts+=1
        if self.phase=="before" and self.scenario=="second_file_failure" and name==deploy.TARGETS[1]:
            # Fail BEFORE the second live file is written.
            raise IOError("SIMULATED_SECOND_FILE_UPLOAD_REJECTED")
        if self.phase=="before" and self.scenario=="partial_second_upload" and name==deploy.TARGETS[1] and data==PATCHED[name]:
            # Interrupted write: byte-exact prefix of the intended candidate.
            self.path(remote).write_bytes(PATCHED[name][:12])
            raise IOError("SIMULATED_PARTIAL_SECOND_UPLOAD")
        if self.phase=="before" and self.scenario=="unknown_second_upload" and name==deploy.TARGETS[1] and data==PATCHED[name]:
            # Unknown bytes could be a concurrent editor; must fail closed.
            self.path(remote).write_bytes(b"THIRD_PARTY_UNKNOWN_CONTENT")
            raise IOError("SIMULATED_UNKNOWN_SECOND_UPLOAD")
        self.path(remote).write_bytes(data)
        assert self.path(remote).read_bytes()==data
        if self.phase=="before" and data==PATCHED[name]:
            assert self.read(remote,token)==PATCHED[name]

    def reload(self,token):
        self.reload_count+=1
        if self.phase=="before":
            self.phase="after_first_reload"

    def healthy(self):
        self.healthy_calls+=1
        if self.scenario=="health_check_failure" and self.healthy_calls==1:
            return False
        if self.scenario=="rollback_health_failure" and self.healthy_calls in (1,2):
            return False
        return True

    def assert_backup(self):
        for name in deploy.TARGETS:
            assert any(path.endswith("/original/"+name) and data==ORIGINAL[name]
                       for path,data in self.backups.items()),"Original not preserved: "+name
            assert any(path.endswith("/candidate/"+name) and data==PATCHED[name]
                       for path,data in self.backups.items()),"Candidate not preserved: "+name
        assert len(self.backups)==4

    def live(self):
        return {name:self.read(deploy.ROOT+"/"+name,"dummy") for name in deploy.TARGETS}

def run_case(scenario, expect_manual=False):
    with tempfile.TemporaryDirectory(prefix="private-drive-pr25-rollback-") as tmp:
        remote=FakeRemote(pathlib.Path(tmp),scenario)
        log=io.StringIO()
        with (
            patch.object(deploy,"secret",return_value="SYNTHETIC_TOKEN"),
            patch.object(deploy,"plan",return_value=(ORIGINAL.copy(),PATCHED.copy())),
            patch.object(deploy,"read",side_effect=remote.read),
            patch.object(deploy,"upload",side_effect=remote.upload),
            patch.object(deploy,"reload",side_effect=remote.reload),
            patch.object(deploy,"healthy",side_effect=remote.healthy),
            patch.dict(os.environ,{"OPERATOR_APPROVED_PR25":"YES"}),
            patch.object(sys,"argv",["pr25_guarded_deploy_NOT_EXECUTED.py","--execute"]),
            contextlib.redirect_stdout(log),
        ):
            try:
                deploy.main()
                raise AssertionError("Failure injection did not trigger")
            except (IOError,RuntimeError) as exc:
                assert "SIMULATED" in str(exc) or "POST_RELOAD_HEALTH_FAILED" in str(exc),str(exc)
        output=log.getvalue()
        remote.assert_backup()
        assert remote.live()==ORIGINAL,"File restoration failed"
        assert remote.reload_count==1 if scenario in ("second_file_failure","partial_second_upload") else remote.reload_count==2
        expected="ROLLBACK_MANUAL_INTERVENTION_REQUIRED" if expect_manual else "ROLLBACK_VERIFIED"
        assert expected in output,(scenario,output)
        assert "PR25_DEPLOY_APPLIED_BASIC_HEALTH_PASSED" not in output
        # Temporary files including all synthetic backups are destroyed here.
        print("PASS",scenario.upper(),"ORIGINAL_BYTES_RESTORED","BACKUPS_VERIFIED",
              "RELOADS",remote.reload_count,"STATUS",expected,flush=True)

# Failure after one file is live, second rejected before writing:
run_case("second_file_failure")
# Failure after both patched files are uploaded, during post-reload availability:
run_case("health_check_failure")
# Interrupted upload must be restored automatically from the checksum-verified
# backup, not from unverified local source bytes.
run_case("partial_second_upload")
# Unknown content must never be overwritten: manual intervention remains required.
with tempfile.TemporaryDirectory(prefix="private-drive-pr25-unknown-") as tmp:
    remote=FakeRemote(pathlib.Path(tmp),"unknown_second_upload")
    log=io.StringIO()
    with (
        patch.object(deploy,"secret",return_value="SYNTHETIC_TOKEN"),
        patch.object(deploy,"plan",return_value=(ORIGINAL.copy(),PATCHED.copy())),
        patch.object(deploy,"read",side_effect=remote.read),
        patch.object(deploy,"upload",side_effect=remote.upload),
        patch.object(deploy,"reload",side_effect=remote.reload),
        patch.object(deploy,"healthy",return_value=True),
        patch.dict(os.environ,{"OPERATOR_APPROVED_PR25":"YES"}),
        patch.object(sys,"argv",["pr25_guarded_deploy_NOT_EXECUTED.py","--execute"]),
        contextlib.redirect_stdout(log),
    ):
        try:
            deploy.main()
            raise AssertionError("Unknown-byte write should fail")
        except IOError:
            pass
    output=log.getvalue()
    remote.assert_backup()
    assert remote.live()["miniapp_server.py"]==ORIGINAL["miniapp_server.py"]
    assert remote.live()["pd_trip_runtime_v4.py"]==b"THIRD_PARTY_UNKNOWN_CONTENT"
    assert "ROLLBACK_CONCURRENT_MODIFICATION_pd_trip_runtime_v4.py" in output
    assert "ROLLBACK_MANUAL_INTERVENTION_REQUIRED" in output
    assert "ROLLBACK_CONTENT_MISMATCH_pd_trip_runtime_v4.py" in output
    print("PASS UNKNOWN_BYTES_FAIL_CLOSED_MANUAL_RECOVERY_REQUIRED",flush=True)

# Do not let a missing operator approval trigger any (mocked) reads or writes.
with patch.object(deploy,"secret",side_effect=AssertionError("No secret reads allowed")), \
     patch.dict(os.environ,{"OPERATOR_APPROVED_PR25":""}), \
     patch.object(sys,"argv",["pr25_guarded_deploy_NOT_EXECUTED.py","--execute"]):
    try:deploy.main()
    except RuntimeError as error:
        assert str(error)=="MISSING_OPERATOR_APPROVAL"
    else:raise AssertionError("Missing approval was accepted")
print("PASS EXECUTE_WITHOUT_APPROVAL_BLOCKED",flush=True)
print("ALL_PR25_ROLLBACK_INJECTION_GATES_PASSED",flush=True)
print("NO_PYTHONANYWHERE_WRITES_OR_EXTERNAL_PAYMENT_REQUESTS",flush=True)
