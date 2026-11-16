"""PR #25 guarded deployment plan (NOT automatically executed).

Requires --execute plus separate OPERATOR_APPROVED_PR25=YES.
Before *any live write*, reads current source, checks expected SHA256,
builds a minimal patch and verifies AST. Writes checked backups of
original and candidate sources, then changes only two files with rollback.

Do NOT run before explicit approval and an operational maintenance window.
No database, order, payment, .env or Telegram API reads/writes.
"""
import argparse
import datetime
import hashlib
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ops.pr25_live_overlay_dryrun import (
    get_live,add_admin_guard,secure_trip_runtime,
    secure_server_tail,verify_ast
)

REPO=pathlib.Path(__file__).resolve().parents[1]
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
DOMAIN="wilsonpark.pythonanywhere.com"
TARGETS=("miniapp_server.py","pd_trip_runtime_v4.py")
# Preflight snapshot from GET-only audit, checked again immediately before writes.
PINNED={
    "miniapp_server.py":"e827dcc675c40195fc01eccaf72ee081472b7a00a0b92e8a814f09711bf04959",
    "pd_trip_runtime_v4.py":"0bee9f529e34000d38f8f09cf76c909aa27d073fabb191ea9e468ce3ba1add62",
}
def sha(data):return hashlib.sha256(data).hexdigest()
def secret():
    token=re.sub(r"^Token\s+","",os.environ.get("PYTHONANYWHERE_API_TOKEN","").strip(),flags=re.I)
    if not token:raise RuntimeError("API_TOKEN_MISSING")
    return token
def api(url, token, method="GET", payload=None, content_type=None):
    headers={"Authorization":"Token "+token}
    if content_type:headers["Content-Type"]=content_type
    with urllib.request.urlopen(urllib.request.Request(url,method=method,headers=headers,data=payload),timeout=50) as resp:
        return resp.status,resp.read(2000001)
def remote_path(path):return API+"/files/path"+path
def read(path,token):
    status,payload=api(remote_path(path),token)
    if status!=200 or not payload:raise RuntimeError("REMOTE_READ_FAILED")
    return payload
def upload(path,data,token):
    boundary="pdpr25uploadboundary"
    filename=path.rsplit("/",1)[-1]
    part=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"{filename}\"\r\n"
          "Content-Type: application/octet-stream\r\n\r\n").encode()
    body=part+data+f"\r\n--{boundary}--\r\n".encode()
    status,_=api(remote_path(path),token,"POST",body,"multipart/form-data; boundary="+boundary)
    if status not in (200,201):raise RuntimeError("REMOTE_WRITE_FAILED")
    if read(path,token)!=data:raise RuntimeError("WRITE_VERIFY_FAILED")
def reload(token):
    status,_=api(API+"/webapps/"+DOMAIN+"/reload/",token,"POST",b"","application/x-www-form-urlencoded")
    if status not in (200,201,202,204):raise RuntimeError("RELOAD_FAILED")
def public_status(path):
    url="https://"+DOMAIN+path
    req=urllib.request.Request(url,headers={"User-Agent":"PrivateDrivePR25Healthcheck/1"},method="GET")
    try:
        with urllib.request.urlopen(req,timeout=25) as res:
            return res.status,res.read(200001)
    except urllib.error.HTTPError as exc:
        return exc.code,b""
def healthy():
    for attempt in range(5):
        try:
            home,body=public_status("/")
            privacy,_=public_status("/privacy")
            legal,_=public_status("/legal")
            orders,_=public_status("/api/orders")
            admin,_=public_status("/api/admin/console/orders")
            if home==privacy==legal==200 and orders in (401,403) and admin in (401,403) and b"pdObLanguage" in body:
                return True
        except (urllib.error.URLError,TimeoutError):
            pass
        time.sleep(3)
    return False
def plan(token):
    if not healthy():raise RuntimeError("PUBLIC_PRECHECK_FAILED")
    originals={}
    for name in TARGETS:
        raw=read(ROOT+"/"+name,token)
        h=sha(raw)
        if h!=PINNED[name]:
            raise RuntimeError("SOURCE_SHA_CHANGED_BLOCK_"+name)
        originals[name]=raw
        print("PINNED_SOURCE_OK",name,h,flush=True)
    server=secure_server_tail(add_admin_guard(originals["miniapp_server.py"].decode("utf-8")))
    runtime=secure_trip_runtime(originals["pd_trip_runtime_v4.py"].decode("utf-8"))
    verify_ast(server,runtime)
    candidate={"miniapp_server.py":server.encode("utf-8"),
               "pd_trip_runtime_v4.py":runtime.encode("utf-8")}
    for name in TARGETS:
        print("CANDIDATE",name,"SHA256",sha(candidate[name]),flush=True)
    return originals,candidate
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    if not args.execute:
        print("DRY_RUN_ONLY_RELEASE_NOT_EXECUTED",flush=True)
        print("PINNED_SOURCE_SHA256",PINNED,flush=True)
        print("NEXT_STEP Explicit authorization plus separate maintenance window required",flush=True)
        return
    if os.environ.get("OPERATOR_APPROVED_PR25")!="YES":
        raise RuntimeError("MISSING_OPERATOR_APPROVAL")
    token=secret()
    old,new=plan(token)
    # Backups must be fully uploaded and readback-verified before touching
    # production. Names are unique per release attempt.
    backup="/home/wilsonpark/private_drive_backups/pr25_"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    for name in TARGETS:
        upload(backup+"/original/"+name,old[name],token)
        upload(backup+"/candidate/"+name,new[name],token)
    print("BACKUPS_AND_CANDIDATES_VERIFIED",backup,flush=True)
    # Re-read to prevent overwriting another operator's changes during backup.
    for name in TARGETS:
        if read(ROOT+"/"+name,token)!=old[name]:
            raise RuntimeError("LIVE_CHANGED_AFTER_BACKUP_ABORT")
    wrote=[]
    try:
        for name in TARGETS:
            # Guard against unexpected concurrent modifications per file.
            if read(ROOT+"/"+name,token)!=old[name]:
                raise RuntimeError("CONCURRENT_CHANGE_BLOCK")
            # Add before writing so even a partial failed write is rolled back.
            wrote.append(name)
            upload(ROOT+"/"+name,new[name],token)
            print("LIVE_PATCH_VERIFIED",name,flush=True)
        reload(token)
        if not healthy():raise RuntimeError("POST_RELOAD_HEALTH_FAILED")
        print("PR25_DEPLOY_APPLIED_BASIC_HEALTH_PASSED",flush=True)
        print("NO_BOOKING_OR_PAYMENT_ENDPOINT_CALLED",flush=True)
    except Exception:
        errors=[]
        # Revert only files matching expected candidate/original bytes; do not
        # clobber third-party modifications during an emergency rollback.
        for name in reversed(wrote):
            try:
                current=read(ROOT+"/"+name,token)
                if current==old[name]:continue
                if current!=new[name]:
                    errors.append("ROLLBACK_CONCURRENT_MODIFICATION_"+name)
                    continue
                upload(ROOT+"/"+name,old[name],token)
            except Exception:
                errors.append("RESTORE_FAILED_"+name)
        try:reload(token)
        except Exception:errors.append("ROLLBACK_RELOAD_FAILED")
        # A successful API response is not proof of rollback: verify bytes
        # and ensure that the restored application is serving requests.
        for name in TARGETS:
            try:
                if read(ROOT+"/"+name,token)!=old[name]:
                    errors.append("ROLLBACK_CONTENT_MISMATCH_"+name)
            except Exception:
                errors.append("ROLLBACK_READBACK_FAILED_"+name)
        try:
            if not healthy():errors.append("ROLLBACK_PUBLIC_HEALTH_FAILED")
        except Exception:errors.append("ROLLBACK_PUBLIC_HEALTH_ERROR")
        print("ROLLBACK_VERIFIED" if not errors else "ROLLBACK_MANUAL_INTERVENTION_REQUIRED",flush=True)
        for e in errors:print(e,flush=True)
        raise
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("DEPLOY_BLOCKED",type(exc).__name__,str(exc)[:140],flush=True)
        raise SystemExit(1)
