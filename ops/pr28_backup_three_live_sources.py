"""Backup three PR28 sources from PythonAnywhere, with complete readback checks.

Writes backup files only to existing private backup folder, no source changes,
no database access, no orders, no payment provider calls, no reload.
"""
import datetime,hashlib,os,re,secrets,urllib.error,urllib.request
USER="wilsonpark"
API="https://www.pythonanywhere.com/api/v0/user/"+USER+"/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
BACKUP="/home/wilsonpark/private_drive_backups/"
FILES={
 "miniapp_server.py":"f4a4dcfe4c9f406e",
 "miniapp/templates/index.html":"402cf5244b743252",
 "Euro_Baltic_Transfer.py":"bf45ff7b4e097e13",
}
def digest(data):return hashlib.sha256(data).hexdigest()
def request(path,token,method="GET",body=None,ctype=None):
    headers={"Authorization":"Token "+token}
    if ctype:headers["Content-Type"]=ctype
    req=urllib.request.Request(API+path,method=method,headers=headers,data=body)
    with urllib.request.urlopen(req,timeout=60) as response:
        return response.status,response.read(2000001)
def download(path,token):
    status,data=request(path,token)
    if status!=200 or not data:raise RuntimeError("BACKUP_READ_FAILED")
    return data
def upload(path,data,token):
    boundary="pdpr28"+secrets.token_hex(16)
    filename=path.rsplit("/",1)[-1]
    prefix=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n").encode()
    body=prefix+data+f"\r\n--{boundary}--\r\n".encode()
    status,_=request(path,token,"POST",body,"multipart/form-data; boundary="+boundary)
    if status not in (200,201):raise RuntimeError("BACKUP_UPLOAD_FAILED")
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    status,_=request(BACKUP,token)
    if status!=200:raise RuntimeError("BACKUP_PARENT_UNAVAILABLE")
    originals={}
    for name,hashprefix in FILES.items():
        data=download(ROOT+name,token)
        h=digest(data)
        if not h.startswith(hashprefix):raise RuntimeError("SOURCE_HASH_CHANGED_BLOCK_"+name)
        originals[name]=data
        print("SOURCE_OK",name,"SHA256",h,"BYTES",len(data),flush=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    ident=stamp+"_"+secrets.token_hex(5)
    for name,data in originals.items():
        path=BACKUP+"pr28_"+ident+"__original__"+name.replace("/","__")
        try:
            request(path,token)
            raise RuntimeError("BACKUP_COLLISION")
        except urllib.error.HTTPError as exc:
            if exc.code!=404:raise
        upload(path,data,token)
        readback=download(path,token)
        if readback!=data or digest(readback)!=digest(data):
            raise RuntimeError("BACKUP_CONTENT_MISMATCH_"+name)
        print("BACKUP_READBACK_OK",name,"PATH",path,"SHA256",digest(data),flush=True)
    for name,data in originals.items():
        if download(ROOT+name,token)!=data:raise RuntimeError("SOURCE_CHANGED_DURING_BACKUP_"+name)
    print("PR28_ALL_THREE_BACKUPS_VERIFIED_NO_LIVE_CHANGES",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("BACKUP_ABORTED",type(e).__name__,str(e)[:110],flush=True)
        raise SystemExit(1)
