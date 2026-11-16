"""Inspect PythonAnywhere bot runtime only through GET endpoints.
Sanitize task commands and console metadata; never print tokens, env or user files.
No POST, PATCH, restart, database or payment operations.
"""
import json,os,re,urllib.error,urllib.request
ROOT="https://www.pythonanywhere.com/api/v0/user/wilsonpark/"
def fetch(uri,token):
    req=urllib.request.Request(ROOT+uri,headers={"Authorization":"Token "+token},method="GET")
    try:
        with urllib.request.urlopen(req,timeout=35) as r:return r.status,json.loads(r.read(400000))
    except urllib.error.HTTPError as e:return e.code,{}
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    for endpoint in ("always_on/","scheduled_tasks/","consoles/"):
        status,data=fetch(endpoint,token)
        print("ENDPOINT",endpoint,"HTTP",status,flush=True)
        # Different PythonAnywhere API versions use list or paginated results.
        rows=data if isinstance(data,list) else data.get("results",[]) if isinstance(data,dict) else []
        if not isinstance(rows,list):rows=[]
        print("ITEMS",endpoint,len(rows),flush=True)
        if rows and isinstance(rows[0],dict):
            print("FIELDS",endpoint,",".join(sorted(k for k in rows[0].keys() if not any(z in k.lower() for z in ("secret","token","password","key")))),flush=True)
        for row in rows:
            if not isinstance(row,dict):continue
            value=" ".join(str(row.get(k,"")) for k in ("command","description","executable","arguments","name","command_line","task","console_name"))
            if re.search(r"Euro_Baltic_Transfer|dating_lithuania|private_drive|miniapp_server|telegram",value,re.I):
                # Only disclose matched classification; redact source command and env.
                kind="private_drive_bot" if "Euro_Baltic_Transfer" in value else "project_related"
                print("MATCH",endpoint,"KIND",kind,"ID",row.get("id","?"),"ENABLED",row.get("enabled","unknown"),flush=True)
    print("BOT_RUNTIME_AUDIT_READ_ONLY_FINISHED",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("BOT_RUNTIME_AUDIT_FAILED",type(e).__name__,flush=True)
        raise SystemExit(1)
