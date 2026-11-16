"""Guarded single HTML PR27 release plan, NOT executed by default.

Only modifies live Mini App HTML after explicit operator approval, actual source
SHA, verified backup/candidate, and health checks. Restores original after
failed/partial update, reloads site, checks restored bytes and public health.
No order/DB/API payment/Telegram state changed.
"""
import argparse,datetime,hashlib,os,pathlib,re,secrets,sys,time,urllib.error,urllib.request
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ops.pr27_live_pilot_overlay_dryrun import overlay,PINNED,HTML,LIVE,API
DOMAIN="wilsonpark.pythonanywhere.com"
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
BACKUP="/home/wilsonpark/private_drive_backups/"
def digest(data):return hashlib.sha256(data).hexdigest()
def api(url,token,method="GET",body=None,ctype=None):
    headers={"Authorization":"Token "+token}
    if ctype:headers["Content-Type"]=ctype
    req=urllib.request.Request(url,headers=headers,method=method,data=body)
    with urllib.request.urlopen(req,timeout=55) as response:
        return response.status,response.read(700000)
def read(path,token):
    status,raw=api(BASE+"/files/path"+path,token)
    if status!=200:raise RuntimeError("REMOTE_READ_FAILED")
    return raw
def upload(path,data,token):
    boundary="pr27"+secrets.token_hex(14)
    fn=path.rsplit("/",1)[-1]
    heading=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"{fn}\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n").encode()
    status,_=api(BASE+"/files/path"+path,token,"POST",
                 heading+data+f"\r\n--{boundary}--\r\n".encode(),
                 "multipart/form-data; boundary="+boundary)
    if status not in (200,201):raise RuntimeError("UPLOAD_FAILED")
    if read(path,token)!=data:raise RuntimeError("UPLOAD_READBACK_MISMATCH")
def reload(token):
    status,_=api(BASE+f"/webapps/{DOMAIN}/reload/",token,"POST",
                 b"","application/x-www-form-urlencoded")
    if status not in (200,201,202,204):raise RuntimeError("RELOAD_FAILED")
def check_public(expected_marker):
    for attempt in range(6):
        try:
            req=urllib.request.Request("https://"+DOMAIN+"/",method="GET",headers={"User-Agent":"PD-Cockpit-Release-Check/1"})
            with urllib.request.urlopen(req,timeout=20) as r:
                text=r.read(700000)
                if r.status==200 and expected_marker in text:return True
        except (urllib.error.URLError,TimeoutError):pass
        time.sleep(3)
    return False
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    if not args.execute:
        print("PR27_DRYRUN_DEFAULT_NOT_EXECUTED",flush=True)
        print("PINNED_ORIGINAL_SHA256",PINNED,flush=True)
        return
    if os.environ.get("OPERATOR_APPROVED_PR27")!="YES":
        raise RuntimeError("OPERATOR_APPROVAL_REQUIRED")
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    source=LIVE+HTML
    old=read(source,token)
    if digest(old)!=PINNED:raise RuntimeError("SOURCE_SHA_MISMATCH_ABORT")
    new=overlay(old.decode("utf8")).encode("utf8")
    if new==old:raise RuntimeError("EMPTY_PATCH")
    if not check_public(b"pdPilotWork"):raise RuntimeError("PRE_DEPLOY_PUBLIC_HEALTH_FAILED")
    status,_=api(BASE+"/files/path"+BACKUP,token)
    if status!=200:raise RuntimeError("BACKUP_PARENT_UNAVAILABLE")
    timestamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    prefix=BACKUP+"pr27_cockpit_"+timestamp+"_"+secrets.token_hex(6)
    original_path=prefix+"__original__index.html"
    candidate_path=prefix+"__candidate__index.html"
    for path in (original_path,candidate_path):
        try:read(path,token)
        except urllib.error.HTTPError as e:
            if e.code!=404:raise
        else:raise RuntimeError("BACKUP_PATH_EXISTS")
    # Backup and candidate are read-back verified before the first live write.
    upload(original_path,old,token);upload(candidate_path,new,token)
    if digest(read(original_path,token))!=digest(old) or read(candidate_path,token)!=new:
        raise RuntimeError("BACKUPS_NOT_VERIFIED")
    if read(source,token)!=old:raise RuntimeError("CONCURRENT_CHANGE_ABORT")
    print("PR27_BACKUP_AND_CANDIDATE_VERIFIED",flush=True)
    attempted=False
    try:
        attempted=True
        upload(source,new,token)
        reload(token)
        if not check_public(b"pd-pilot-cockpit-adapter-stage-js"):
            raise RuntimeError("POST_DEPLOY_HEALTH_FAILED")
        print("PR27_COCKPIT_INSTALLED_AND_PUBLIC_VERIFIED",flush=True)
    except Exception:
        problems=[]
        if attempted:
            try:
                current=read(source,token)
                if current!=old:
                    if current!=new and not (0<len(current)<len(new) and new.startswith(current)):
                        problems.append("UNKNOWN_CONCURRENT_CONTENT")
                    else:
                        original=read(original_path,token)
                        if digest(original)!=digest(old):
                            problems.append("BACKUP_HASH_INVALID")
                        else:upload(source,original,token)
            except Exception:problems.append("RESTORE_UPLOAD_FAILED")
        try:reload(token)
        except Exception:problems.append("RESTORE_RELOAD_FAILED")
        try:
            if read(source,token)!=old:problems.append("RESTORE_HASH_FAILED")
            if not check_public(b"pdPilotWork"):problems.append("RESTORE_PUBLIC_HEALTH_FAILED")
        except Exception:problems.append("RESTORE_VERIFY_FAILED")
        print("PR27_ROLLBACK_VERIFIED" if not problems else "PR27_MANUAL_RECOVERY_REQUIRED",flush=True)
        for p in problems:print(p,flush=True)
        raise
if __name__=="__main__":
    try:main()
    except Exception as error:
        print("PR27_DEPLOY_BLOCKED",type(error).__name__,str(error)[:100],flush=True)
        raise SystemExit(1)
