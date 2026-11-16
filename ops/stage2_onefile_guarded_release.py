"""Stage2 explanation-only production release; defaults to no-write.

User-approved one-file HTML patch. Exact SHA pin, verification of fresh
original+candidate backup readbacks, no modifications to DB/orders/images.
On failure, restore original HTML and reload website. Never auto-deploy from main.
"""
import argparse,datetime,hashlib,os,re,secrets,sys,time,urllib.error,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.stage2_ui_live_compatible_dryrun import patch,EXPECTED
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
LIVE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
BACKUPS="/home/wilsonpark/private_drive_backups/"
DOMAIN="wilsonpark.pythonanywhere.com"
CANDIDATE_SHA="6d78db07c62b31e7fcee9de55dc822a5c99250484aa7443ecc2af19fb54f88b2"
def sha(data):return hashlib.sha256(data).hexdigest()
def call(url,token,method="GET",data=None,ctype=None):
    headers={"Authorization":"Token "+token}
    if ctype:headers["Content-Type"]=ctype
    req=urllib.request.Request(url,headers=headers,method=method,data=data)
    with urllib.request.urlopen(req,timeout=50) as response:
        return response.status,response.read(800000)
def get(path,token):
    status,data=call(API+"/files/path"+path,token)
    if status!=200 or not data:raise RuntimeError("REMOTE_GET_INCOMPLETE")
    return data
def put(path,data,token):
    boundary="pdstage2"+secrets.token_hex(12)
    filename=path.rsplit("/",1)[-1]
    head=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"{filename}\"\r\n"
          "Content-Type: application/octet-stream\r\n\r\n").encode()
    status,_=call(API+"/files/path"+path,token,"POST",head+data+
                  f"\r\n--{boundary}--\r\n".encode(),
                  "multipart/form-data; boundary="+boundary)
    if status not in (200,201):raise RuntimeError("UPLOAD_FAILED")
    if get(path,token)!=data:raise RuntimeError("REMOTE_UPLOAD_READBACK_FAILED")
def reload(token):
    status,_=call(API+f"/webapps/{DOMAIN}/reload/",token,"POST",b"",
                  "application/x-www-form-urlencoded")
    if status not in (200,201,202,204):raise RuntimeError("WEB_RELOAD_FAILED")
def public(expected):
    for attempt in range(5):
        try:
            req=urllib.request.Request("https://"+DOMAIN+"/",headers={"User-Agent":"PrivateDrive-Stage2-ReadonlyReleaseCheck/1"})
            with urllib.request.urlopen(req,timeout=15) as r:
                data=r.read(800000)
                if r.status==200 and expected in data:return True
        except (urllib.error.URLError,TimeoutError):pass
        time.sleep(3)
    return False
def main():
    arg=argparse.ArgumentParser();arg.add_argument("--execute",action="store_true")
    args=arg.parse_args()
    if not args.execute:
        print("STAGE2_PRODUCTION_RELEASE_NOT_EXECUTED",flush=True)
        return
    if os.environ.get("PD_APPROVED_STAGE2_UI")!="YES":
        raise RuntimeError("OPERATOR_APPROVAL_REQUIRED")
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    source=get(LIVE,token)
    if sha(source)!=EXPECTED:raise RuntimeError("SOURCE_HASH_CHANGED_ABORT")
    candidate=patch(source.decode("utf8")).encode("utf8")
    if sha(candidate)!=CANDIDATE_SHA:raise RuntimeError("CANDIDATE_SHA_INVALID")
    if not public(b"pd-pilot-cockpit-adapter-stage-js"):
        raise RuntimeError("PUBLIC_PRE_RELEASE_UNHEALTHY")
    status,_=call(API+"/files/path"+BACKUPS,token)
    if status!=200:raise RuntimeError("BACKUP_DIRECTORY_NOT_FOUND")
    timestamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    prefix=BACKUPS+"stage2_only_"+timestamp+"_"+secrets.token_hex(5)
    original=prefix+"__original_index.html";replacement=prefix+"__candidate_index.html"
    for path in (original,replacement):
        try:get(path,token)
        except urllib.error.HTTPError as error:
            if error.code!=404:raise
        else:raise RuntimeError("BACKUP_COLLISION")
    put(original,source,token)
    put(replacement,candidate,token)
    if get(original,token)!=source or get(replacement,token)!=candidate:
        raise RuntimeError("BACKUP_READBACK_ERROR")
    print("BACKUP_ORIGINAL_PATH",original,flush=True)
    print("BACKUP_CANDIDATE_PATH",replacement,flush=True)
    print("BACKUP_SHA256",sha(source),flush=True)
    print("CANDIDATE_SHA256",sha(candidate),flush=True)
    if get(LIVE,token)!=source:raise RuntimeError("CONCURRENT_SOURCE_CHANGE")
    print("PASS STAGE2_BACKUP_VERIFIED_BEFORE_LIVE_WRITE",flush=True)
    attempted=False
    try:
        attempted=True
        put(LIVE,candidate,token)
        reload(token)
        if not public(b"function pdStage2ApprovalHint(a,missingPhotos)"):
            raise RuntimeError("PUBLIC_STAGE2_HINT_NOT_VISIBLE")
        if get(LIVE,token)!=candidate:raise RuntimeError("POSTRELEASE_SHA_MISMATCH")
        print("STAGE2_ONLY_PRODUCTION_DEPLOYED_AND_VERIFIED",flush=True)
    except Exception:
        faults=[]
        if attempted:
            try:
                now=get(LIVE,token)
                if now!=source:
                    if now!=candidate and not (0<len(now)<len(candidate) and candidate.startswith(now)):
                        faults.append("CONCURRENT_UNEXPECTED_FILE_CONTENT")
                    elif sha(get(original,token))!=EXPECTED:
                        faults.append("RESTORE_BACKUP_HASH_MISMATCH")
                    else:put(LIVE,source,token)
            except Exception:faults.append("BACKUP_RESTORE_ERROR")
        try:reload(token)
        except Exception:faults.append("RESTORED_WEB_RELOAD_FAILED")
        try:
            if get(LIVE,token)!=source:faults.append("RESTORE_BYTES_MISMATCH")
            if not public(b"pd-pilot-cockpit-adapter-stage-js"):faults.append("RESTORED_PUBLIC_HEALTH_FAILED")
        except Exception:faults.append("RESTORE_AUDIT_ERROR")
        print("STAGE2_ROLLBACK_VERIFIED" if not faults else "STAGE2_MANUAL_RECOVERY_REQUIRED",flush=True)
        for item in faults:print("ERROR",item,flush=True)
        raise
if __name__=="__main__":
    try:main()
    except Exception as error:
        print("STAGE2_RELEASE_BLOCKED",type(error).__name__,str(error)[:110],flush=True)
        raise SystemExit(1)
