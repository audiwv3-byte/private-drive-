"""PRIVATE DRIVE: repair driver live-trip map, keep map without GPS, full-screen on double-tap.
Exact SHA-guarded diff to (1) runtime v4 JS, (2) pilot v4 JS, (3) live HTML inline
admin-driver status handler. Only HTML/JS; no order, payment or DB writes.
Preflight Node/Jinja, remote backups of all 3 files, public verification, rollback.
"""
import os,re,hashlib,time,json,tempfile,subprocess
from pathlib import Path
from jinja2 import Environment
import requests

ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE="https://wilsonpark.pythonanywhere.com/"
FILES={
 "pd_trip_runtime_v4.js":"a0569eac3c8b601dbd1aab684ae4d7d22b46cce6823d8a03221c3c5936f05785",
 "pd_pilot_cabinet_v4.js":"b95bd067a79956adc91c06255e786b2ec8953ef9716e6c2090e0cfc4e3e49ab9",
 "miniapp/templates/index.html":"bd2920e1b7dac3461617d3f5717766d63074905c13d0202ea1d692a71e42d927"
}
token="".join(re.sub(r"^Token\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
if not token:raise RuntimeError("Hosting API credentials missing")
sess=requests.Session();sess.headers={"Authorization":"Token "+token}
if sess.get(BASE+"/cpu/",timeout=30).status_code!=200:
    raise RuntimeError("Hosting authentication unavailable")
last=0.
def api(method,path,**kwargs):
    global last
    if path.startswith("/files/path"):
        time.sleep(max(0,1.8-(time.monotonic()-last)))
        last=time.monotonic()
    for a in range(3):
        r=sess.request(method,BASE+path,timeout=45,**kwargs)
        if r.status_code==429 and a<2:
            time.sleep(14*(a+1));continue
        if not r.ok:raise RuntimeError("Hosting API "+method+" failed HTTP "+str(r.status_code))
        return r

def read(path):return api("GET","/files/path"+path).content
def write(path,data):
    api("POST","/files/path"+path,files={"content":("private-drive-driver-map",data,"text/plain")})
    if read(path)!=data:raise RuntimeError("Hosting readback differs: "+path)
def sha(data):return hashlib.sha256(data).hexdigest()

original={}
for path,expected in FILES.items():
    data=read(ROOT+path)
    if sha(data)!=expected:raise RuntimeError("CONCURRENT_SOURCE_CHANGE no writes: "+path+" "+sha(data))
    original[path]=data
raw={p:v.decode("utf-8-sig") for p,v in original.items()}
script=raw["pd_trip_runtime_v4.js"]
pilot=raw["pd_pilot_cabinet_v4.js"]
html=raw["miniapp/templates/index.html"]

# Runtime changes are intentionally limited to the live map/view layer.
old_decl="let active=null,dialog=null,body=null,map=null,marker=null,watch=null,watchOrder=null,lastPositionSent=0,polling=false,hubBusy=false,lastRender=null,locationCircle=null,locationText=null;"
new_decl=old_decl+"\nlet tripMapExpanded=false,tripMapExit=null,tripMapSyncBusy=false;"
if script.count(old_decl)!=1:raise RuntimeError("Live trip declarations changed")

helpers=r"""
// Shared pilot/dispatcher map is available before GPS and never fabricates a car marker.
const tripMapStyles=document.createElement('style');
tripMapStyles.id='pd-trip-driver-fullscreen-20261109';
tripMapStyles.textContent=[
 '#pdTripRuntimeV4.pd-trip-map-expanded{position:fixed!important;inset:0!important;width:100vw!important;height:100dvh!important;max-height:none!important;max-width:none!important;margin:0!important;padding:0!important;border:0!important;border-radius:0!important;overflow:hidden!important;background:#090b10!important}',
 '#pdTripRuntimeV4 .pd-trip-map-canvas{height:320px;min-height:240px;margin:14px 0;border:1px solid #9c854f;border-radius:13px;touch-action:manipulation}',
 '#pdTripRuntimeV4 .pd-trip-map-canvas.pd-trip-map-viewport{position:fixed!important;inset:0!important;width:100vw!important;height:100dvh!important;min-height:100dvh!important;margin:0!important;border:0!important;border-radius:0!important;z-index:8!important}',
 '#pdTripRuntimeV4 .pd-trip-map-close{position:fixed!important;z-index:10000!important;right:calc(env(safe-area-inset-right,0px) + 16px)!important;top:calc(env(safe-area-inset-top,0px) + 16px)!important;border:1px solid #d6ad5b!important;background:#151515!important;color:#f7dfac!important;border-radius:14px!important;min-height:52px!important;padding:12px 18px!important;font-size:16px!important}'
].join('\n');
document.head.append(tripMapStyles);
function pdSetTripMapExpanded(value){
 tripMapExpanded=Boolean(value);
 if(dialog)dialog.classList.toggle('pd-trip-map-expanded',tripMapExpanded);
 const canvas=map?.getContainer();
 if(canvas)canvas.classList.toggle('pd-trip-map-viewport',tripMapExpanded);
 if(tripMapExpanded&&dialog&&!tripMapExit){
  tripMapExit=document.createElement('button');
  tripMapExit.type='button';tripMapExit.className='pd-trip-map-close';
  tripMapExit.textContent=label('Свернуть карту','Close full-screen map','Uždaryti žemėlapį');
  tripMapExit.setAttribute('aria-label',tripMapExit.textContent);
  tripMapExit.onclick=()=>pdSetTripMapExpanded(false);
  dialog.append(tripMapExit);
 }else if(!tripMapExpanded&&tripMapExit){
  tripMapExit.remove();tripMapExit=null;
 }
 if(map)setTimeout(()=>map?.invalidateSize(),100);
}
async function pdUpdateFullTripMap(){
 if(!tripMapExpanded||!active||!map||tripMapSyncBusy||document.hidden)return;
 tripMapSyncBusy=true;
 try{
  const id=active,r=await requestTrip(id);
  if(active!==id||!map)return;
  if(!['Подтверждена','В пути'].includes(r.status)){
   pdSetTripMapExpanded(false);await refresh();return;
  }
  if(Number.isFinite(r.lat)&&Number.isFinite(r.lon)){
   const point=[r.lat,r.lon];
   if(marker)marker.setLatLng(point);
   else marker=L.marker(point).addTo(map);
   if(locationCircle){locationCircle.setLatLng(point);locationCircle.setRadius(Math.min(r.accuracy||0,1000))}
   else locationCircle=L.circle(point,{radius:Math.min(r.accuracy||0,1000)}).addTo(map);
   if(!map.getBounds().contains(point))map.panTo(point);
  }
 }catch(_){/* Last visible map remains; no position guessed on network failure. */}
 finally{tripMapSyncBusy=false}
}
"""
script=script.replace(old_decl,new_decl,1)
anchor="function cleanDialog(){"
if script.count(anchor)!=1:raise RuntimeError("Trip modal cleanup changed")
script=script.replace(anchor,helpers+"\n"+anchor,1)
old_clean="function cleanDialog(){stopPosition();closing(false);if(map)map.remove();map=null;marker=null;locationCircle=null;locationText=null;lastRender=null;dialog=null;body=null;active=null}"
new_clean="function cleanDialog(){pdSetTripMapExpanded(false);stopPosition();closing(false);if(map)map.remove();map=null;marker=null;locationCircle=null;locationText=null;lastRender=null;dialog=null;body=null;active=null}"
if script.count(old_clean)!=1:raise RuntimeError("Live trip cleanup changed")
script=script.replace(old_clean,new_clean,1)

start=script.find("  if(live&&Number.isFinite(r.lat)&&Number.isFinite(r.lon)&&window.L){")
end=script.find("  if(r.role==='passenger'&&!r.wait_accepted_at",start)
if start<0 or end<start:raise RuntimeError("Live-trip map section changed")
old_map=script[start:end]
if "map=L.map(box)" not in old_map or "Ожидаем геопозицию пилота" not in old_map or "locationText=p(" not in old_map:
    raise RuntimeError("Unexpected live-trip mapping implementation")

new_map=r"""  // Pilot/dispatcher sees the map even before the first authorized GPS fix.
  const showWorkingMap=live&&Boolean(window.L)&&(['pilot','admin'].includes(r.role));
  if(live&&Boolean(window.L)&&(hasLocation||showWorkingMap)){
   const point=hasLocation?[r.lat,r.lon]:[55.1694,23.8813];
   const box=document.createElement('div');
   box.className='pd-trip-map-canvas';
   box.setAttribute('role','region');
   box.setAttribute('aria-label',label('Карта текущей поездки','Current trip map','Dabartinės kelionės žemėlapis'));
   body.append(box);
   map=L.map(box,{doubleClickZoom:false}).setView(point,hasLocation?15:7);
   L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);
   if(hasLocation){
    marker=L.marker(point).addTo(map);
    locationCircle=L.circle(point,{radius:Math.min(r.accuracy||0,1000)}).addTo(map);
    locationText=p(r.location_stale?label('Последняя геопозиция устарела — положение сейчас неизвестно.','Location is stale — current position is unknown.','Vietovė pasenusi — dabartinė padėtis nežinoma.'):label('Местоположение пилота · обновлено: ','Pilot location · updated: ','Piloto vietovė · atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString());
   }else{
    locationText=p(label('Карта открыта. Местоположение машины появится после разрешения GPS; показана общая карта Литвы, не координаты водителя.','Map ready. The vehicle appears after GPS permission; this is a general Lithuania map, not the driver location.','Žemėlapis paruoštas. Automobilis bus rodomas leidus GPS; dabar rodomas bendras Lietuvos žemėlapis.'));
   }
   // Disable the built-in double-tap zoom: double-tap expands/collapses the map.
   map.doubleClickZoom.disable();
   map.on('dblclick',()=>pdSetTripMapExpanded(!tripMapExpanded));
   if(showWorkingMap)body.append(button(label('⛶ На весь экран · или дважды нажми карту','⛶ Full screen · or double-tap the map','⛶ Per visą ekraną · arba dukart bakstelėkite'),()=>pdSetTripMapExpanded(true)));
   pdSetTripMapExpanded(tripMapExpanded);
   setTimeout(()=>map?.invalidateSize(),100);
  }else if(live){
   p(label('Карта временно недоступна. Проверьте соединение и перезапустите Mini App.','Map is temporarily unavailable. Check connection and reopen the Mini App.','Žemėlapis laikinai nepasiekiamas.'));
  }
"""
script=script[:start]+new_map+script[end:]
timer="setInterval(()=>{if(!document.hidden){refresh();hubs()}},10000);"
if script.count(timer)!=1:raise RuntimeError("Location refresh timer changed")
script=script.replace(timer,"setInterval(()=>{if(!document.hidden){if(tripMapExpanded)pdUpdateFullTripMap();else refresh();hubs()}},10000);",1)

# After a successful departure from the pilot list, open the existing V4 trip
# panel with map. The route status mutation itself remains unchanged.
pilot_old="await window.pdBeginPickupV4(Number(order.id));await pdPilotWork()"
pilot_new="await window.pdBeginPickupV4(Number(order.id));await pdPilotWork();await window.pdOpenLiveTripV4(Number(order.id))"
if pilot.count(pilot_old)!=1:raise RuntimeError("Pilot departure handler changed")
pilot=pilot.replace(pilot_old,pilot_new,1)

# In the admin-as-driver pane, the status API is unchanged; only navigate to
# the already-existing live-trip map after it reports success.
old_handler="async function pdDriverStatus(id,status){try{await api('/api/admin/status',{id,status});message(pdL(\"Статус обновлён\"));await pdDriverLoad()}catch(e){message(pdL(e.message),true)}}"
new_handler="async function pdDriverStatus(id,status){try{await api('/api/admin/status',{id,status});message(pdL(\"Статус обновлён\"));await pdDriverLoad();if(status==='В пути'&&typeof window.pdOpenLiveTripV4==='function')await window.pdOpenLiveTripV4(id)}catch(e){message(pdL(e.message),true)}}"
if html.count(old_handler)!=1:raise RuntimeError("Admin-as-driver status handler changed")
html=html.replace(old_handler,new_handler,1)

modified={"pd_trip_runtime_v4.js":script,"pd_pilot_cabinet_v4.js":pilot,"miniapp/templates/index.html":html}

# Check the modified JS independently, including every inline script of the template.
with tempfile.TemporaryDirectory() as tmp:
    for n,name in enumerate(("pd_trip_runtime_v4.js","pd_pilot_cabinet_v4.js")):
        fp=Path(tmp)/(str(n)+".js");fp.write_text(modified[name],encoding="utf8")
        out=subprocess.run(["node","--check",str(fp)],capture_output=True,text=True)
        if out.returncode:raise RuntimeError("Live JS syntax "+name+": "+out.stderr[-600:])
    Environment().parse(html)
    for n,js in enumerate(re.findall(r"<script\b[^>]*>([\s\S]*?)</script>",html)):
        if not js.strip() or "{{" in js or "{%" in js:continue
        fp=Path(tmp)/(f"inline_{n}.js");fp.write_text(js,encoding="utf8")
        out=subprocess.run(["node","--check",str(fp)],capture_output=True,text=True)
        if out.returncode:raise RuntimeError("Inline JS invalid "+str(n)+": "+out.stderr[-350:])

    # No live order changes: simulate map-exposure and toggle behavior on plain
    # mocked objects, without loading Leaflet or calling production endpoints.
    check=Path(tmp)/"mock_map.cjs"
    check.write_text(r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
let expanded=[],invalidated=0;const close={remove(){this.removed=true}};
function make(){return {classList:{toggle:(c,on)=>expanded.push([c,on])},append:()=>{},dataset:{}}}
const dialog=make(),canvas=make();
const ctx={window:{PD_LANG:'ru'},document:{createElement:()=>Object.assign(make(),{setAttribute(){}}),head:{append(){}}},
  label:(ru)=>ru,dialog,map:{getContainer:()=>canvas,invalidateSize:()=>invalidated++},
  tripMapExpanded:false,tripMapExit:null,setTimeout:f=>f(),active:99,tripMapSyncBusy:false};
const fn=process.argv[2];
vm.createContext(ctx);
vm.runInContext(fn,ctx);
vm.runInContext('pdSetTripMapExpanded(true)',ctx);
assert.equal(ctx.tripMapExpanded,true);
assert(expanded.some(v=>v[0]==='pd-trip-map-viewport'&&v[1]===true));
vm.runInContext('pdSetTripMapExpanded(false)',ctx);
assert.equal(ctx.tripMapExpanded,false);
assert(expanded.some(v=>v[0]==='pd-trip-map-viewport'&&v[1]===false));
assert(invalidated>=2);
console.log('DRIVER_MAP_FULLSCREEN_TEST_PASS expand=true collapse=true invalidate=true');
""",encoding="utf8")
    fn=script[script.index("function pdSetTripMapExpanded(value){"):script.index("async function pdUpdateFullTripMap(){")]
    out=subprocess.run(["node",str(check),fn],capture_output=True,text=True)
    if out.returncode:raise RuntimeError("Full-screen mock failure "+out.stderr[-900:])
    print(out.stdout.strip(),flush=True)
assert "L.map(box,{doubleClickZoom:false})" in script
assert "map.on('dblclick',()=>pdSetTripMapExpanded(!tripMapExpanded))" in script
assert "const showWorkingMap=live&&Boolean(window.L)&&(['pilot','admin'].includes(r.role))" in script
assert "'/api/admin/status'" in html
assert "await window.pdOpenLiveTripV4(id)" in html
assert "await window.pdOpenLiveTripV4(Number(order.id))" in pilot
assert "await window.pdBeginPickupV4(Number(order.id))" in pilot
assert len(modified)==3
print("DRIVER_MAP_PREFLIGHT_PASS templates=1 scripts=2 Jinja=true Node=true double_tap=true GPS_fallback=true status_API_unchanged=true",flush=True)

if os.environ.get("PD_DRIVER_MAP_DEPLOY")!="1":
    print("DRIVER_MAP_DRY_RUN_PASS hosting_writes=0 orders_writes=0",flush=True)
    raise SystemExit(0)

runid=os.environ.get("GITHUB_RUN_ID","")
if not runid.isdigit():raise RuntimeError("Missing run ID")
backup=f"/home/wilsonpark/private_drive_backups/driver_map_fullscreen_20261109_{runid}/"
# Backup all files and verify before touching anything live.
for path,data in original.items():
    write(backup+path,data)
write(backup+"MANIFEST.json",json.dumps({"files":{p:{"sha256":sha(original[p]),"bytes":len(original[p])} for p in FILES}}).encode())
print("DRIVER_MAP_BACKUP_VERIFIED",backup,flush=True)
for path,data in original.items():
    if read(ROOT+path)!=data:raise RuntimeError("Concurrent live change before update "+path)
written=[]
try:
    for path,content in modified.items():
        written.append(path)
        write(ROOT+path,content.encode("utf8"))
    try:api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:
        print("RELOAD_RESPONSE_TIMEOUT, verifying public assets",flush=True)
    ok=False
    for attempt in range(9):
        responses=[requests.get(SITE+path,params={"trip_map_fix":runid,"attempt":attempt},headers={"Cache-Control":"no-cache"},timeout=30) for path in ("/","/assets/pd-trip-runtime-v4.js","/assets/pd-pilot-cabinet-v4.js")]
        page,runtime,pilots=responses
        ok=(all(r.status_code==200 for r in responses)
            and "pd-trip-driver-fullscreen-20261109" in runtime.text
            and "map.on('dblclick',()=>pdSetTripMapExpanded(!tripMapExpanded))" in runtime.text
            and "showWorkingMap" in runtime.text
            and "await window.pdOpenLiveTripV4(Number(order.id))" in pilots.text
            and "await window.pdOpenLiveTripV4(id)" in page.text
            and "id=\"pdPilotWork\"" in page.text
            and "id=\"pdDriverOrders\"" in page.text)
        print("DRIVER_MAP_PUBLIC_CHECK",attempt,"html",page.status_code,"runtime",runtime.status_code,"pilot",pilots.status_code,"verified",ok,flush=True)
        if ok:break
        time.sleep(5)
    if not ok:raise RuntimeError("Public map/driver UI verification failed")
    print("DRIVER_MAP_LIVE_VERIFIED HTTP=200 map_without_GPS=true double_tap_fullscreen=true admin_driver_open=true pilot_open=true backend_unchanged=true",flush=True)
except BaseException:
    for path in written:
        write(ROOT+path,original[path])
    try:api("POST","/webapps/wilsonpark.pythonanywhere.com/reload/")
    except requests.exceptions.ReadTimeout:pass
    for path in written:
        if read(ROOT+path)!=original[path]:
            raise RuntimeError("ROLLBACK_READBACK_FAILED "+path)
    print("DRIVER_MAP_ROLLBACK_VERIFIED",flush=True)
    raise
