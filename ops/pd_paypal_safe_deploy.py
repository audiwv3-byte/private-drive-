"""Deploy PayPal routes dormant, preserving current production code with auto rollback.

Only two existing production files can be updated, after checksum-verified
off-path backups. No DB/orders/.env/PayPal access. Runtime PayPal feature is
hard-disabled regardless of mode configured in .env. Reads code via GET,
writes exact content by PythonAnywhere multipart file API and reloads app.
"""
import ast, datetime, hashlib, os, pathlib, re, subprocess, tempfile, time
import urllib.error, urllib.request

API="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
RAW="https://raw.githubusercontent.com/audiwv3-byte/private-drive-/caba0b9dd005e13b11f76e8f11788a4599db4926/"
DOMAIN="wilsonpark.pythonanywhere.com"
FILES=("miniapp_server.py","miniapp/templates/index.html")
def token_value():
    value=os.environ.get("PYTHONANYWHERE_API_TOKEN","").strip()
    value=re.sub(r"^Token\s+","",value,flags=re.I)
    if not value:raise ValueError("API_TOKEN_MISSING")
    return value
def request_api(url,token=None,method="GET",body=None,ctype=None):
    headers={"Authorization":"Token "+token} if token else {}
    if ctype:headers["Content-Type"]=ctype
    request=urllib.request.Request(url,headers=headers,method=method,data=body)
    with urllib.request.urlopen(request,timeout=50) as res:
        payload=res.read(2000001)
        return res.status,payload
def file_url(path):
    return API+"/files/path"+path
def get_file(path,token):
    status,content=request_api(file_url(path),token)
    if status!=200 or not content:raise ValueError("FILE_GET_FAILED")
    return content
def public_get(path="/"):
    request=urllib.request.Request("https://"+DOMAIN+path,
                                   headers={"User-Agent":"PrivateDriveSafeRollout/1.0"},
                                   method="GET")
    try:
        with urllib.request.urlopen(request,timeout=30) as res:
            return res.status, res.read(200000)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
def checksum(payload):return hashlib.sha256(payload).hexdigest()
def upload(path,payload,token):
    boundary="pd_paypal_integration_upload_boundary_20261116"
    pre=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"{path.rsplit('/',1)[-1]}\"\r\n"
         "Content-Type: application/octet-stream\r\n\r\n").encode()
    body=pre+payload+f"\r\n--{boundary}--\r\n".encode()
    status,_=request_api(file_url(path),token,"POST",body,"multipart/form-data; boundary="+boundary)
    if status not in (200,201):raise ValueError("FILE_POST_STATUS")
    if get_file(path,token)!=payload:raise ValueError("FILE_WRITE_VERIFY_FAILED")
def replace_one(source,anchor,replacement):
    if source.count(anchor)!=1:raise ValueError("LIVE_SOURCE_ANCHOR_CHANGED")
    return source.replace(anchor,replacement,1)
def between(text,start,end):
    if text.count(start)!=1 or text.count(end)!=1:raise ValueError("PR_MARKER_MISSING")
    return text[text.index(start):text.index(end,text.index(start)+len(start))]
def build(live,ref):
    server=live["miniapp_server.py"].decode("utf-8")
    html=live["miniapp/templates/index.html"].decode("utf-8")
    pr=ref["miniapp_server.py"]
    pr_html=ref["miniapp/templates/index.html"]
    guard="PD_PAYPAL_DEPLOY_GATE = False  # hard-disabled until reviewed sandbox activation\n"
    server=replace_one(server,"import pd_fixed_prices\n",
                       "import pd_fixed_prices\nimport pd_paypal_checkout as pd_paypal\n"+guard)
    field_start=pr.index("paypal_available=bool(pd_paypal.settings())")
    field_end=pr.index(",\n",field_start)+1
    field=pr[field_start:field_end]
    if len(field)>450:raise ValueError("PR_FIELD_LENGTH_INVALID")
    field=field.replace("bool(pd_paypal.settings())",
                        "(PD_PAYPAL_DEPLOY_GATE and bool(pd_paypal.settings()))",1)
    marker="card_link=r['card_payment_url'] if r['status']=='Подтверждена' else '',"
    server=replace_one(server,marker,marker+"\n       "+field)
    block=between(pr,"# PayPal is OFF by default","# Stripe: the secret key")
    block=replace_one(block,"def paypal_ready():\n    cfg = pd_paypal.settings()",
                      "def paypal_ready():\n    if not PD_PAYPAL_DEPLOY_GATE:\n        return None\n    cfg = pd_paypal.settings()")
    server=replace_one(server,"# Stripe: the secret key",block+"# Stripe: the secret key")
    ast.parse(server)
    for route in ("/paypal/config","/paypal/create","/paypal/capture"):
        if server.count(route)!=1:raise ValueError("PAYPAL_ROUTE_COUNT")
    if server.count("PD_PAYPAL_DEPLOY_GATE = False")!=1:
        raise ValueError("SAFETY_GATE_MISSING")
    dynamic_anchor="()=>cryptoNotice(id)]]){"
    dynamic_replacement="()=>cryptoNotice(id)],...(p.paypal_available?[[pdReleaseText('💙 PayPal','💙 PayPal','💙 PayPal'),()=>paypalNotice()]]:[])]){"
    html=replace_one(html,dynamic_anchor,dynamic_replacement)
    js=between(pr_html,"// PayPal is available only for a confirmed","async function cashNotice()")
    html=replace_one(html,"async function cashNotice()",js+"async function cashNotice()")
    if html.count("async function paypalNotice()")!=1:raise ValueError("PAYPAL_HANDLER_COUNT")
    # Compile only changed scripts; unrelated inline JSON/scripts can be non-JS.
    scripts=re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>",html,flags=re.I)
    originals=re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>",
                         live["miniapp/templates/index.html"].decode("utf-8"),flags=re.I)
    if len(scripts)!=len(originals):raise ValueError("SCRIPT_TAG_NUMBER")
    changed=0
    for (_,body),(_,old) in zip(scripts,originals):
        if body==old:continue
        with tempfile.TemporaryDirectory(prefix="pd-js-") as temp:
            name=pathlib.Path(temp)/"inline.js"
            name.write_text(body,encoding="utf-8")
            result=subprocess.run(["node","--check",str(name)],capture_output=True)
            if result.returncode!=0:raise ValueError("MODIFIED_JAVASCRIPT_SYNTAX_INVALID")
        changed+=1
    if changed!=1:raise ValueError("JS_PATCH_COUNT")
    print("OVERLAY_COMPILED checked_modified_scripts",changed,flush=True)
    return {"miniapp_server.py":server.encode("utf-8"),
            "miniapp/templates/index.html":html.encode("utf-8")}
def reload(token):
    url=API+"/webapps/"+DOMAIN+"/reload/"
    code,_=request_api(url,token,"POST",b"","application/x-www-form-urlencoded")
    if code not in (200,201,202,204):raise ValueError("WEBAPP_RELOAD_FAILED")
def healthy():
    for attempt in range(5):
        try:
            code,body=public_get("/")
            code2,_=public_get("/privacy")
            code3,_=public_get("/legal")
            private,_=public_get("/api/orders")
            if code==code2==code3==200 and private in (401,403) and b"pdObLanguage" in body:
                return True
        except (urllib.error.URLError,TimeoutError):
            pass
        time.sleep(3)
    return False
def main():
    token=token_value()
    if not healthy():raise ValueError("PREDEPLOY_PUBLIC_HEALTH_FAILED")
    raw={}
    for p in FILES:
        raw[p]=get_file(ROOT+"/"+p,token)
    module=get_file(ROOT+"/pd_paypal_checkout.py",token)
    reviewed_module=request_api(RAW+"pd_paypal_checkout.py")[1]
    if checksum(module)!=checksum(reviewed_module):
        raise ValueError("PAYPAL_MODULE_DIFFERS_FROM_REVIEWED_PR")
    reviewed={p:request_api(RAW+p)[1].decode("utf-8") for p in FILES}
    candidate=build(raw,reviewed)
    backup="/home/wilsonpark/private_drive_backups/auto_paypal_"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("SAFETY_GATES_OK",flush=True)
    for p in FILES:
        upload(backup+"/original/"+p,raw[p],token)
    for p in FILES:
        upload(backup+"/staged/"+p,candidate[p],token)
    print("BACKUP_AND_STAGING_VERIFIED",flush=True)
    if any(get_file(ROOT+"/"+p,token)!=raw[p] for p in FILES):
        raise ValueError("LIVE_CHANGED_SINCE_AUDIT_ABORT")
    wrote=[]
    try:
        for p in FILES:
            upload(ROOT+"/"+p,candidate[p],token)
            wrote.append(p)
        print("FILES_UPDATED_AND_VERIFIED",len(wrote),flush=True)
        reload(token)
        if not healthy():raise ValueError("POSTDEPLOY_PUBLIC_HEALTH_FAILED")
        print("DEPLOY_SUCCESS",flush=True)
        print("PAYPAL_RUNTIME_HARD_DISABLED",flush=True)
        print("NO_ORDERS_OR_PAYMENT_API_CALLED",flush=True)
    except Exception:
        print("DEPLOY_EXCEPTION_AUTO_ROLLBACK",flush=True)
        errors=0
        for p in FILES:
            try:upload(ROOT+"/"+p,raw[p],token)
            except Exception:errors+=1
        try:reload(token)
        except Exception:errors+=1
        print("ROLLBACK_VERIFIED" if errors==0 else "ROLLBACK_MANUAL_REVIEW_REQUIRED",flush=True)
        raise
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("RELEASE_ERROR",type(exc).__name__,str(exc)[:100],flush=True)
        raise SystemExit(1)
