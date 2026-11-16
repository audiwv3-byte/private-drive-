"""PR28 three-file guarded deployment, NEVER automatically invoked.

Guards: approved operator, known current SHA256, verified backup readback,
actual matching PRIVATE DRIVE always-on task to restart bot, syntax/diff checks.
Rolls back all candidate/prefix writes and restarts webapp/bot on failure.

No DB access, no order creation, no real payment calls, no env or secret reads
from PythonAnywhere. Running with no --execute prints safe readiness only.
"""
import argparse,ast,datetime,hashlib,json,os,pathlib,re,secrets,subprocess,sys,tempfile,time,urllib.error,urllib.request
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ops.cash_offline_overlay_dryrun import candidate
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
FILES=("miniapp_server.py","miniapp/templates/index.html","Euro_Baltic_Transfer.py")
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
BACKUP="/home/wilsonpark/private_drive_backups/"
PINNED={
"miniapp_server.py":"f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4",
"miniapp/templates/index.html":"402cf5244b74325285122aa87604b4ba700df9072a5389d55f527243bd99796d",
"Euro_Baltic_Transfer.py":"bf45ff7b4e097e13c2c5d12e7d22df7d8e6c274ea073867299ecfcc8d1649462"}
DOMAIN="wilsonpark.pythonanywhere.com"
def sha(data):return hashlib.sha256(data).hexdigest()
def api(url,token,method="GET",body=None,ctype=None):
    headers={"Authorization":"Token "+token}
    if ctype:headers["Content-Type"]=ctype
    req=urllib.request.Request(url,method=method,data=body,headers=headers)
    with urllib.request.urlopen(req,timeout=50) as r:return r.status,r.read(2000001)
def read(path,token):
    status,bytes_=api(BASE+"/files/path"+path,token)
    if status!=200 or not bytes_:raise RuntimeError("GET_VERIFY_FAILED")
    return bytes_
def put(path,data,token):
    boundary="pdpr28"+secrets.token_hex(16)
    filename=path.rsplit("/",1)[-1]
    head=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"{filename}\"\r\n"
          "Content-Type: application/octet-stream\r\n\r\n").encode()
    status,_=api(BASE+"/files/path"+path,token,"POST",head+data+f"\r\n--{boundary}--\r\n".encode(),
                  "multipart/form-data; boundary="+boundary)
    if status not in (200,201):raise RuntimeError("UPLOAD_FAILED")
    if read(path,token)!=data:raise RuntimeError("UPLOAD_READBACK_FAILED")
def bot_task(token):
    status,body=api(BASE+"/always_on/",token)
    if status!=200:raise RuntimeError("BOT_TASKS_UNAVAILABLE")
    payload=json.loads(body)
    tasks=payload if isinstance(payload,list) else payload.get("results",[])
    found=[t for t in tasks if isinstance(t,dict) and
           "Euro_Baltic_Transfer.py" in str(t.get("command","")) and t.get("enabled",True)]
    if len(found)!=1:raise RuntimeError("BOT_RESTART_CONTROL_NOT_VERIFIED")
    ident=found[0].get("id")
    if not isinstance(ident,int):raise RuntimeError("BOT_TASK_ID_MISSING")
    return ident
def restart_bot(token,taskid):
    status,_=api(BASE+f"/always_on/{taskid}/restart/",token,"POST",b"",
                 "application/x-www-form-urlencoded")
    if status not in (200,201,202,204):raise RuntimeError("BOT_RESTART_FAILED")
def reload_web(token):
    status,_=api(BASE+f"/webapps/{DOMAIN}/reload/",token,"POST",b"",
                 "application/x-www-form-urlencoded")
    if status not in (200,201,202,204):raise RuntimeError("WEBAPP_RELOAD_FAILED")
def smoke():
    # Public endpoint checks only. No user/order endpoint writes, no login.
    for attempt in range(5):
        try:
            with urllib.request.urlopen("https://"+DOMAIN+"/",timeout=15) as r:
                html=r.read(400000)
                if r.status==200 and b"pdbPays" in html and b"data-method=\"\xd0\x9d\xd0\xb0\xd0\xbb\xd0\xb8\xd1\x87\xd0\xbd" not in html:
                    return True
        except (urllib.error.URLError,TimeoutError):
            pass
        time.sleep(3)
    return False
def build(old):
    modified=candidate(*(old[name].decode("utf-8") for name in FILES))
    new={name:text.encode("utf-8") for name,text in zip(FILES,modified)}
    ast.parse(new["miniapp_server.py"].decode())
    ast.parse(new["Euro_Baltic_Transfer.py"].decode())
    with tempfile.TemporaryDirectory(prefix="pd-pr28-release-dry-") as tmp:
        for name in ("miniapp_server.py","Euro_Baltic_Transfer.py"):
            p=pathlib.Path(tmp)/name
            p.write_bytes(new[name])
            subprocess.run([sys.executable,"-m","py_compile",str(p)],capture_output=True,check=True)
    return new
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--execute",action="store_true")
    args=p.parse_args()
    if not args.execute:
        print("READINESS_ONLY_DEPLOYMENT_NOT_EXECUTED",flush=True)
        print("PRODUCTION_FILES",",".join(FILES),flush=True)
        print("AUTOMATIC_BOT_RESTART_VERIFICATION_REQUIRED",flush=True)
        return
    if os.environ.get("OPERATOR_APPROVED_PR28")!="YES":
        raise RuntimeError("OPERATOR_APPROVAL_REQUIRED")
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    taskid=bot_task(token) # Important: no writes until this check passes.
    originals={name:read(ROOT+name,token) for name in FILES}
    for name in FILES:
        if sha(originals[name])!=PINNED[name]:raise RuntimeError("SOURCE_HASH_CONFLICT_"+name)
        print("SOURCE_PINNED",name,flush=True)
    next_version=build(originals)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")+"_"+secrets.token_hex(4)
    stem=BACKUP+"pr28_release_"+stamp
    def bp(kind,name):return stem+"__"+kind+"__"+name.replace("/","__")
    for name in FILES:
        put(bp("original",name),originals[name],token)
        put(bp("candidate",name),next_version[name],token)
    for name in FILES:
        if read(ROOT+name,token)!=originals[name]:
            raise RuntimeError("CONCURRENT_SOURCE_CHANGE_ABORT_"+name)
    print("BACKUPS_AND_CANDIDATES_VERIFIED",flush=True)
    wrote=[]
    try:
        for name in FILES:
            if read(ROOT+name,token)!=originals[name]:
                raise RuntimeError("CONCURRENT_WRITE_DETECTED_"+name)
            wrote.append(name) # Include partial failure in rollback.
            put(ROOT+name,next_version[name],token)
            print("FILE_INSTALLED_WITH_READBACK",name,flush=True)
        reload_web(token)
        restart_bot(token,taskid)
        if not smoke():raise RuntimeError("POST_DEPLOY_SMOKE_FAILED")
        print("PR28_DEPLOY_SUCCEEDED_WITH_BOT_RESTART",flush=True)
    except Exception:
        problems=[]
        for name in reversed(wrote):
            try:
                now=read(ROOT+name,token)
                if now==originals[name]:continue
                if now!=next_version[name] and not (0<len(now)<len(next_version[name]) and next_version[name].startswith(now)):
                    problems.append("UNKNOWN_CHANGED_FILE_"+name)
                    continue
                old=read(bp("original",name),token)
                if sha(old)!=PINNED[name]:
                    problems.append("BACKUP_HASH_FAILED_"+name);continue
                put(ROOT+name,old,token)
            except Exception:
                problems.append("RESTORE_FAILED_"+name)
        for op in (reload_web,lambda t:restart_bot(t,taskid)):
            try:op(token)
            except Exception:problems.append("PROCESS_RESTART_FAILED")
        for name in FILES:
            try:
                if read(ROOT+name,token)!=originals[name]:
                    problems.append("RESTORED_HASH_FAILED_"+name)
            except Exception:
                problems.append("RESTORED_READ_FAILED_"+name)
        print("ROLLBACK_VERIFIED" if not problems else "MANUAL_RECOVERY_REQUIRED",flush=True)
        for x in problems:print(x,flush=True)
        raise
if __name__=="__main__":
    try:main()
    except Exception as err:
        print("RELEASE_BLOCKED",type(err).__name__,str(err)[:105],flush=True)
        raise SystemExit(1)
