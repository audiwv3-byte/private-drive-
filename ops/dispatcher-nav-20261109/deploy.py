"""Remove the passenger-mode switch from the authenticated dispatcher UI only.
Precise live-template patch, backup, HTML+Jinja+JS and isolated nav regression checks.
No customer or order records accessed; server/business/payment routes unchanged.
"""
import hashlib,json,os,re,subprocess,tempfile,time
from pathlib import Path
import requests
from jinja2 import Environment

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILE="miniapp/templates/index.html"
SITE="https://wilsonpark.pythonanywhere.com/"
EXPECTED_SHA="62435256a5f782cc71ea3f0af65395a18ff0ba15137f9e6c6651a21f8f704563"
ROLE_BUTTON="""<button type="button" data-mode="client" onclick="pdSetRole('client')">Клиент</button>"""
NAV_BUTTON=r"""<button class=\"secondary\" onclick=\"pdSetRole('client')\">Как клиент</button>"""
token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token:raise RuntimeError("Hosting API credentials not available")
s=requests.Session();s.headers={"Authorization":"Token "+token}
r=s.get(BASE+"/cpu/",timeout=30)
if r.status_code!=200:raise RuntimeError("Hosting authentication unavailable")
last=0.
def api(method,path,**kwargs):
    global last
    if path.startswith("/files/path"):
        time.sleep(max(0,1.65-(time.monotonic()-last)))
        last=time.monotonic()
    for attempt in range(3):
        response=s.request(method,BASE+path,timeout=45,**kwargs)
        if response.status_code==429 and attempt<2:
            time.sleep(14*(attempt+1))
            continue
        if not response.ok:raise RuntimeError("Hosting API "+method+" "+str(response.status_code))
        return response

def read(path):
    return api("GET","/files/path"+path).content

def write(path,body):
    api("POST","/files/path"+path,files={"content":("pd-dispatch-nav",body,"text/html")})
    if read(path)!=body:raise RuntimeError("Hosting source readback did not match")

def digest(b):return hashlib.sha256(b).hexdigest()

original=read(ROOT+FILE)
if digest(original)!=EXPECTED_SHA:
    raise RuntimeError("LIVE_TEMPLATE_CHANGED: no writes; hash="+digest(original))
source=original.decode("utf-8-sig")
if source.count(ROLE_BUTTON)!=1 or source.count(NAV_BUTTON)!=1:
    raise RuntimeError("Unexpected role bar or bottom nav structure; no writes")
if source.count("function pdSetRole(mode){")!=1:
    raise RuntimeError("Role handler changed; no writes")
changed=source.replace(ROLE_BUTTON,"",1).replace(NAV_BUTTON,"",1)
assert len(source)-len(changed)==len(ROLE_BUTTON)+len(NAV_BUTTON)
assert changed.count(ROLE_BUTTON)==changed.count(NAV_BUTTON)==0
assert 'data-mode="admin"' in changed and 'data-mode="driver"' in changed
assert r"""onclick=\"pdSetRole('admin')\">Диспетчерская""" in changed
assert r"""onclick=\"pdSetRole('driver')\">Водитель""" in changed
assert 'function pdSetRole(mode){' in changed
assert 'id="pdObPassenger"' in changed
assert 'id="pdCustomers"' in changed
assert 'id="pdLangSelect"' in changed
Environment().parse(changed)

# Run navigation regression with simulated admin to prove only dispatcher and
# driver switches are emitted for admin/driver views.
func=re.search(r"function pdSetRole\(mode\)\{[\s\S]*?\n\}",changed)
assert func,"pdSetRole missing after patch"
with tempfile.TemporaryDirectory() as tmp:
    fp=Path(tmp)/"dispatcher_nav.cjs"
    js=r"""
const vm=require('node:vm'), assert=require('node:assert/strict');
const fn=process.argv[2];
const nav={innerHTML:''};
const roleButtons=[
  {dataset:{mode:'admin'},classList:{toggle(){}},setAttribute(){}},
  {dataset:{mode:'driver'},classList:{toggle(){}},setAttribute(){}}
];
const body={classList:{toggle(){}},dataset:{}};
const ctx={
  admin:true,window:{pdAccessUser:{admin:true}},document:{body,querySelectorAll:()=>roleButtons},
  $:(id)=>id==='mainNav'?nav:null,
  pdApplyRoleAccess:()=>{},pdL:x=>x,go:()=>{},
  message:()=>{throw Error('Unexpected admin access denial')}
};
vm.createContext(ctx);vm.runInContext(fn,ctx);
for(const mode of ['admin','driver']){
  vm.runInContext("pdSetRole('"+mode+"')",ctx);
  assert(nav.innerHTML.includes('Диспетчерская'),'Dispatcher navigation missing');
  assert(nav.innerHTML.includes('Водитель'),'Driver navigation missing');
  assert(!nav.innerHTML.includes('Как клиент'),'Passenger switch present');
  assert(!nav.innerHTML.includes("pdSetRole('client')"),'Client role action present');
  assert.equal((nav.innerHTML.match(/<button/g)||[]).length,2);
}
console.log("DISPATCHER_NAV_TEST_PASS two_roles_only=true role_switch_works=true");
"""
    fp.write_text(js,encoding="utf-8")
    p=subprocess.run(["node",str(fp),func.group()],capture_output=True,text=True)
    if p.returncode:raise RuntimeError("Navigation test failed: "+p.stderr[-500:])
    print(p.stdout.strip(),flush=True)
    for i,jsbody in enumerate(re.findall(r'<script\b[^>]*>([\s\S]*?)</script>',changed)):
        if not jsbody.strip() or "{{" in jsbody or "{%" in jsbody:continue
        path=Path(tmp)/(f"inline{i}.js")
        path.write_text(jsbody,encoding="utf-8")
        check=subprocess.run(["node","--check",str(path)],capture_output=True,text=True)
        if check.returncode:
            raise RuntimeError("JavaScript syntax "+str(i)+": "+check.stderr[-500:])
print("DISPATCHER_NAV_PREFLIGHT_PASS Jinja=true JavaScript=true nav_and_role_buttons_only=true business_logic_unchanged=true",flush=True)
if os.environ.get("PD_NAV_DEPLOY")!="1":
    print("DISPATCHER_NAV_DRY_RUN_PASS live_writes=0",flush=True)
    raise SystemExit(0)

runid=os.environ.get("GITHUB_RUN_ID","")
if not runid.isdigit():raise RuntimeError("CI run identifier not available")
backup=f"/home/wilsonpark/private_drive_backups/dispatcher_no_client_{runid}/"
write(backup+FILE,original)
write(backup+"SOURCE_MANIFEST.json",json.dumps({"file":FILE,"source_sha256":digest(original),"bytes":len(original)}).encode("utf8"))
print("DISPATCHER_NAV_BACKUP_VERIFIED",backup,flush=True)
if read(ROOT+FILE)!=original:raise RuntimeError("Concurrent live source change; no writes")
did_write=False
try:
    did_write=True
    write(ROOT+FILE,changed.encode("utf8"))
    try:
        api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:
        print("RELOAD_API_TIMED_OUT verifying public output instead",flush=True)
    success=False
    for attempt in range(8):
        response=requests.get(SITE,params={"nav_fix":runid,"attempt":attempt},headers={"Cache-Control":"no-cache"},timeout=30)
        markup=response.text
        success=(response.status_code==200 and ROLE_BUTTON not in markup and
                 NAV_BUTTON not in markup and
                 r"""onclick=\"pdSetRole('admin')\">Диспетчерская""" in markup and
                 r"""onclick=\"pdSetRole('driver')\">Водитель""" in markup and
                 'id="pdCustomers"' in markup and 'id="pdLangSelect"' in markup)
        print("DISPATCHER_NAV_PUBLIC_SMOKE",attempt,"http",response.status_code,"verified",success,flush=True)
        if success:break
        time.sleep(4)
    if not success:raise RuntimeError("Live public navigation verification failed")
    print("DISPATCHER_NAV_LIVE_VERIFIED HTTP=200 client_switch_removed=true dispatcher_driver_kept=true orders_unchanged=true",flush=True)
except BaseException:
    if did_write:
        write(ROOT+FILE,original)
        try:
            api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
        except requests.exceptions.ReadTimeout:pass
        if read(ROOT+FILE)!=original:raise RuntimeError("Failed to verify source rollback")
        print("DISPATCHER_NAV_ROLLBACK_VERIFIED",flush=True)
    raise
