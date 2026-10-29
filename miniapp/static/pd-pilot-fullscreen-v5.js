/* PRIVATE DRIVE pilot-only fullscreen map; loaded after trip runtime. */
(()=>{
'use strict';
let dlg=null,map=null,marker=null,target=null,routeLine=null,actions=null,tripId=null,latest=null,refreshing=false,timerBaseMs=0;
const l=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const trip=(id,path='',data)=>api('/api/trip/'+Number(id)+path,data);
const timeFmt=s=>{const n=Math.max(0,Math.floor(s||0));return [Math.floor(n/3600),Math.floor(n%3600/60),n%60].map(v=>String(v).padStart(2,'0')).join(':')};
function btn(text,fn){const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=text;b.style.cssText='min-height:45px;flex:1 1 140px';b.onclick=async()=>{
 b.disabled=true;try{await fn()}catch(e){showError(e.message||String(e))}finally{b.disabled=false}};return b}
function showError(text){if(typeof message==='function')message(text,true);else window.alert(text)}
function close(){
 const current=dlg;dlg=null;tripId=null;latest=null;actions=null;
 if(map)map.remove();map=null;marker=null;target=null;routeLine=null;
 if(current?.open)current.close();
}
async function action(name){
 if(!tripId)return;
 await trip(tripId,'/action',{action:name});
 if(name==='finish'){close();if(typeof pdCheckTripCompletion==='function')pdCheckTripCompletion();return}
 await update();
}
function waze(r){
 const dest=r.route_destination||'';
 const url=Number.isFinite(r.route_lat)&&Number.isFinite(r.route_lon)?
  'https://waze.com/ul?ll='+encodeURIComponent(r.route_lat+','+r.route_lon)+'&navigate=yes':
  'https://waze.com/ul?q='+encodeURIComponent(dest)+'&navigate=yes';
 if(window.Telegram?.WebApp?.openLink)window.Telegram.WebApp.openLink(url);
 else window.open(url,'_blank','noopener');
}
async function editRoute(){
 if(!tripId)return;
 const d=pdSimpleDialog(l('Изменить маршрут','Change route','Keisti maršrutą'));
 const input=document.createElement('input');input.type='text';input.maxLength=200;input.placeholder=l('Новый адрес назначения','New destination address','Naujas kelionės tikslas');
 input.style.cssText='width:100%;margin:10px 0';
 const note=document.createElement('p');
 note.textContent=l('Новый адрес начнёт действовать только после подтверждения пассажира. Цена не меняется автоматически. Изменяйте маршрут только после остановки автомобиля.',
 'Passenger approval is required. Fare does not change automatically. Make changes only while safely parked.',
 'Reikia keleivio patvirtinimo. Kaina automatiškai nesikeičia. Keiskite maršrutą tik saugiai sustoję.');
 d.append(input,note,btn(l('Отправить пассажиру','Send to passenger','Siųsti keleiviui'),async()=>{
  await trip(tripId,'/route-change',{destination:input.value});
  d.close();await update();
 }));
 input.focus();
}
function drawPosition(r){
 if(!map)return;
 if(Number.isFinite(r.lat)&&Number.isFinite(r.lon)){
  const pos=[r.lat,r.lon];
  if(!marker){marker=L.marker(pos).addTo(map);map.setView(pos,15)}else marker.setLatLng(pos);
 }
 if(Number.isFinite(r.route_lat)&&Number.isFinite(r.route_lon)){
  const coords=[r.route_lat,r.route_lon];
  if(!target)target=L.marker(coords).addTo(map);else target.setLatLng(coords);
  if(marker){
   const points=[marker.getLatLng(),target.getLatLng()];
   if(!routeLine)routeLine=L.polyline(points,{color:'#d8b66b',dashArray:'7,9',weight:3}).addTo(map);
   else routeLine.setLatLngs(points);
  }
 }else{
  if(target)target.remove();target=null;
  if(routeLine)routeLine.remove();routeLine=null;
 }
}
function render(r){
 if(!dlg||!actions)return;
 if(r.role!=='pilot'||!['Подтверждена','В пути'].includes(r.status)){close();return}
 latest=r;timerBaseMs=Date.now();drawPosition(r);
 actions.replaceChildren();
 const caption=document.createElement('div');caption.style.cssText='flex:1 1 100%;font-size:13px;font-weight:600';
 caption.textContent=l('Заказ №','Order #','Užsakymas Nr. ')+tripId+' · '+r.status+' · '+l('Куда: ','To: ','Į: ')+(r.route_destination||'—');
 actions.append(caption);
 const stop=document.createElement('div');stop.id='pdFullStopClock';stop.style.cssText='flex:1 1 100%;font-size:20px;font-weight:700';actions.append(stop);
 if(r.route_pending){
  const pending=document.createElement('div');pending.style.cssText='flex:1 1 100%;font-size:12px';
  pending.textContent=l('Ожидается согласие пассажира: ','Passenger confirmation pending: ','Laukiamas keleivio sutikimas: ')+r.route_pending.destination;
  actions.append(pending);
 }
 if(r.status==='В пути'){
  actions.append(btn(r.stop_active?l('В путь','Resume','Tęsti kelionę'):l('Остановка','Stop','Sustojimas'),()=>action(r.stop_active?'resume':'pause')));
  actions.append(btn(l('Изменить маршрут','Change route','Keisti maršrutą'),editRoute));
  actions.append(btn(l('Завершить поездку','Finish trip','Baigti kelionę'),async()=>{
   if(r.stop_active)throw Error(l('Сначала завершите остановку кнопкой «В путь»','Resume before finishing','Prieš baigdami tęskite kelionę'));
   if(!window.confirm(l('Завершить поездку №','Finish trip #','Baigti kelionę Nr. ')+tripId+'?'))return;
   await action('finish');
  }));
 }
 actions.append(btn('Waze',()=>waze(r)));
 actions.append(btn(l('Свернуть карту','Minimize map','Sumažinti žemėlapį'),()=>close()));
 tick();
}
function tick(){
 if(!latest||!dlg)return;
 const e=dlg.querySelector('#pdFullStopClock');if(!e)return;
 const n=Number(latest.stop_seconds||0)+(latest.stop_active?Math.max(0,Math.floor((Date.now()-timerBaseMs)/1000)):0);
 e.textContent=l('Ожидание на остановках: ','Stop time: ','Sustojimo trukmė: ')+timeFmt(n);
}
async function update(){
 if(!dlg||!tripId||refreshing)return;
 refreshing=true;
 try{const r=await trip(tripId);if(dlg&&tripId===Number(r.order_id))render(r)}
 catch(e){showError(e.message||String(e))}
 finally{refreshing=false}
}
window.pdPilotFullMapV5=async function(id){
 const number=Number(id);if(!Number.isSafeInteger(number)||number<=0||!window.L)return;
 if(dlg){if(tripId===number){map?.invalidateSize();return}close()}
 let r;try{r=await trip(number)}catch(e){showError(e.message);return}
 if(r.role!=='pilot'||!['Подтверждена','В пути'].includes(r.status))return;
 tripId=number;
 dlg=pdSimpleDialog(l('Карта пилота','Pilot map','Piloto žemėlapis'));
 dlg.id='pdFullPilotMapV5';
 dlg.style.cssText='inset:0;margin:0;padding:0;border:0;border-radius:0;width:100vw;max-width:100vw;height:100dvh;max-height:100dvh;overflow:hidden;background:#111722;color:white';
 const header=dlg.querySelector('.pd-info-header');
 if(header)header.style.cssText='position:absolute;z-index:1200;top:10px;left:10px;right:10px;border-radius:12px;background:#101722ed;padding:8px 12px;color:white';
 const surface=document.createElement('div');surface.style.cssText='position:absolute;inset:0';dlg.append(surface);
 actions=document.createElement('div');actions.style.cssText='position:absolute;z-index:1200;bottom:0;left:0;right:0;display:flex;gap:8px;flex-wrap:wrap;align-items:center;max-height:46dvh;overflow:auto;padding:12px 12px calc(12px + env(safe-area-inset-bottom));color:white;background:#111722ed';
 dlg.append(actions);
 dlg.addEventListener('close',()=>{if(dlg){close()}},{once:true});
 map=L.map(surface,{doubleClickZoom:false,zoomControl:true}).setView(Number.isFinite(r.lat)&&Number.isFinite(r.lon)?[r.lat,r.lon]:[54.6872,25.2797],Number.isFinite(r.lat)&&Number.isFinite(r.lon)?15:10);
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(map);
 render(r);setTimeout(()=>{map?.invalidateSize()},60);
};
setInterval(()=>{tick();if(dlg&&!document.hidden)update()},10000);
setInterval(tick,1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&dlg)update()});
})();
