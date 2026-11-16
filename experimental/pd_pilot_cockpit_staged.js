/* PRIVATE DRIVE Cockpit — isolated experimental map-first pilot UI.
 * NOT wired into production. No dispatcher/passenger UI mutation.
 * API is supplied explicitly by the integration adapter; no payments.
 */
(function(root){
'use strict';
const messages={
 ru:{title:'Кабина пилота',gpsOn:'GPS включён',gpsOff:'Включить GPS',gpsStop:'Отключить GPS',
  idle:'Ожидание назначенного заказа',load:'Загружаем назначенные поездки…',
  arrived:'Прибыл',start:'В путь',finish:'Завершить',toward:'К пассажиру',
  stop:'Остановка',unavailable:'Нет доступа к геолокации',connection:'Нет связи с сервером',
  permission:'Нет допуска пилота',loading:'Загрузка',trip:'Заказ',route:'Маршрут',
  gpsHelp:'GPS передаётся только пока приложение открыто и доступ разрешён.'},
 en:{title:'Pilot cockpit',gpsOn:'GPS active',gpsOff:'Enable GPS',gpsStop:'Disable GPS',
  idle:'Waiting for assigned trips',load:'Loading assigned trips…',
  arrived:'Arrived',start:'Start trip',finish:'Finish',toward:'Navigate to pickup',
  stop:'Stop',unavailable:'Location permission unavailable',connection:'Connection lost',
  permission:'Pilot access required',loading:'Loading',trip:'Order',route:'Route',
  gpsHelp:'Location is shared only while the app is open and permission is granted.'},
 lt:{title:'Piloto kabina',gpsOn:'GPS įjungtas',gpsOff:'Įjungti GPS',gpsStop:'Išjungti GPS',
  idle:'Laukiama priskirtų užsakymų',load:'Įkeliami užsakymai…',
  arrived:'Atvykau',start:'Pradėti kelionę',finish:'Baigti',toward:'Į paėmimo vietą',
  stop:'Sustojimas',unavailable:'Vietos prieiga negalima',connection:'Nėra ryšio',
  permission:'Nėra piloto prieigos',loading:'Įkeliama',trip:'Užsakymas',route:'Maršrutas',
  gpsHelp:'Vieta perduodama tik atvėrus programėlę ir gavus leidimą.'}
};
const liveStatuses=['Подтверждена','В пути'];
function nextAction(order){
 if(!order||!liveStatuses.includes(order.status))return null;
 if(order.status==='Подтверждена')return order.arrived_at?'start':'arrive';
 return 'finish';
}
function pickActive(orders){
 if(!Array.isArray(orders))return null;
 return orders.find(o=>o&&liveStatuses.includes(o.status))||null;
}
function coords(lat,lon){return Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180}
function make(opts){
 if(!opts||!opts.api||!opts.leaflet||!opts.document)throw Error('Cockpit dependencies missing');
 const doc=opts.document,L=opts.leaflet,api=opts.api,lang=messages[opts.lang]||messages.ru;
 const getGeo=()=>opts.geolocation||root.navigator?.geolocation;
 const windowRef=opts.window||root;
 let mountNode=null,container=null,map=null,marker=null,watch=null,watchId=0,selected=null;
 let disposed=false,polling=false,latestPosition=null,requestPending=false,lastSent=0,refreshInterval=null;
 let gpsEnabled=false,viewReady=false;
 let elements={};
 function el(tag,klass,text){
   const e=doc.createElement(tag);if(klass)e.className=klass;
   if(text!==undefined)e.textContent=String(text);return e;
 }
 function updateGps(){
   if(!elements.gps)return;
   elements.gps.textContent=gpsEnabled?lang.gpsOn:lang.gpsOff;
   elements.gps.disabled=gpsEnabled;elements.gps.hidden=gpsEnabled;
   if(elements.gpsStop)elements.gpsStop.hidden=!gpsEnabled;
   if(elements.gpsStatus)elements.gpsStatus.textContent=gpsEnabled?lang.gpsOn:lang.gpsOff;
 }
 function stopGps(){
   const old=watch;
   watch=null;watchId++;
   gpsEnabled=false;
   const geo=getGeo();
   if(old!==null&&geo?.clearWatch)geo.clearWatch(old);
   updateGps();
 }
 function updateMap(lat,lon){
   if(!coords(lat,lon)||!map)return;
   if(!marker){marker=L.marker([lat,lon]).addTo(map);}
   else marker.setLatLng([lat,lon]);
   map.panTo([lat,lon],{animate:false});
 }
 function gpsStart(){
   if(disposed||gpsEnabled||!selected)return;
   const geo=getGeo();if(!geo?.watchPosition){displayError(lang.unavailable);return;}
   const thisWatch=++watchId;gpsEnabled=true;updateGps();
   try{
    const id=selected.id;
    watch=geo.watchPosition(async position=>{
      if(disposed||watchId!==thisWatch||doc.hidden||selected?.id!==id)return;
      const latitude=position?.coords?.latitude,longitude=position?.coords?.longitude;
      if(!coords(latitude,longitude))return;
      latestPosition={latitude,longitude};updateMap(latitude,longitude);
      if(requestPending||Date.now()-lastSent<5000)return;
      requestPending=true;lastSent=Date.now();
      try{await api('/api/trip/'+Number(id)+'/location',{lat:latitude,lon:longitude,accuracy:position.coords.accuracy});}
      catch(e){stopGps();displayError(e?.message||lang.connection);}
      finally{requestPending=false;}
    },()=>{stopGps();displayError(lang.unavailable);},
    {enableHighAccuracy:true,maximumAge:5000,timeout:15000});
   }catch(e){stopGps();displayError(e?.message||lang.unavailable);}
 }
 function displayError(text){if(elements.status)elements.status.textContent=text;}
 function navPickup(){
   if(!selected)return;
   const url='https://waze.com/ul?q='+encodeURIComponent(selected.origin||'')+'&navigate=yes';
   if(selected.origin&&opts.openNavigation)opts.openNavigation(url);
 }
 async function action(which){
   if(!selected||disposed||!['arrive','start','finish'].includes(which))return;
   const allowed=nextAction(selected);
   if(allowed!==which)return;
   if(which==='finish')stopGps();
   await api('/api/trip/'+Number(selected.id)+'/action',{action:which});
   await refresh();
 }
 function renderOrder(){
   if(!elements.order||disposed)return;
   elements.order.replaceChildren();
   if(!selected){elements.order.append(el('p','pd-cockpit-idle',lang.idle));return;}
   const order=selected,heading=el('strong','',lang.trip+' №'+Number(order.id));
   elements.order.append(heading);
   const from=el('p','pd-cockpit-route',[order.origin,order.destination].filter(Boolean).join(' → '));
   elements.order.append(from);
   const actions=el('div','pd-cockpit-actions');
   const navigate=el('button','',lang.toward);navigate.type='button';navigate.onclick=navPickup;
   actions.append(navigate);
   const nxt=nextAction(order);
   if(nxt){
     const caption=nxt==='arrive'?lang.arrived:nxt==='start'?lang.start:lang.finish;
     const ctl=el('button','',caption);ctl.type='button';ctl.dataset.action=nxt;
     ctl.onclick=async()=>{ctl.disabled=true;try{await action(nxt);}catch(e){displayError(e.message);}finally{ctl.disabled=false;}};
     actions.append(ctl);
   }
   if(order.status==='В пути'&&opts.onStop){
     const stop=el('button','',lang.stop);stop.type='button';
     stop.onclick=()=>opts.onStop(order.id);actions.append(stop);
   }
   elements.order.append(actions);
 }
 async function refresh(){
   if(disposed||polling)return;polling=true;
   try{
     const result=await api('/api/driver/work');
     if(disposed)return;
     if(!result||!Array.isArray(result.orders))throw Error(lang.connection);
     // Server MUST independently filter orders for approved pilot.
     const previous=selected?.id;
     selected=pickActive(result.orders);
     if(previous!==selected?.id)stopGps();
     renderOrder();if(elements.status)elements.status.textContent='';
   }catch(e){displayError(e?.message||lang.connection);}
   finally{polling=false;}
 }
 function mount(target,verifiedPilotAccess){
   if(disposed)throw Error('Disposed cockpit');
   if(!verifiedPilotAccess)return false; // Applicant must never see trip UI.
   if(container)return true;
   mountNode=target;
   container=el('section','pd-pilot-cockpit');
   container.id='pdPilotCockpit';container.setAttribute('aria-label',lang.title);
   container.innerHTML=''; // Only our newly created node. Never touch other roles.
   const mapNode=el('div','pd-pilot-cockpit-map');mapNode.id='pdPilotCockpitMap';
   const head=el('div','pd-cockpit-top');
   head.append(el('strong','',lang.title));
   const gpsStatus=el('span','pd-cockpit-gps-status',lang.gpsOff);head.append(gpsStatus);
   const panel=el('div','pd-cockpit-bottom'),order=el('div','pd-cockpit-order'),
         controls=el('div','pd-cockpit-gps-controls');
   const gps=el('button','',lang.gpsOff);gps.type='button';gps.onclick=gpsStart;
   const gpsStop=el('button','',lang.gpsStop);gpsStop.type='button';gpsStop.onclick=stopGps;gpsStop.hidden=true;
   controls.append(gps,gpsStop);
   const status=el('p','pd-cockpit-status');status.setAttribute('role','status');
   panel.append(order,controls,status);
   container.append(mapNode,head,panel);
   target.append(container);
   elements={gps,gpsStop,gpsStatus,order,status};
   map=L.map(mapNode,{zoomControl:false}).setView([54.6872,25.2797],12);
   L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
       {attribution:'© OpenStreetMap contributors'}).addTo(map);
   viewReady=true;
   if(map.invalidateSize)map.invalidateSize();
   renderOrder();updateGps();refresh();
   refreshInterval=windowRef.setInterval?.(()=>{if(!doc.hidden)refresh();},10000)||null;
   return true;
 }
 function unmount(){
   stopGps();
   if(refreshInterval!==null)windowRef.clearInterval?.(refreshInterval);
   refreshInterval=null;
   if(map)map.remove();
   map=null;marker=null;viewReady=false;
   if(container?.parentNode)container.parentNode.removeChild(container);
   container=null;mountNode=null;selected=null;elements={};
 }
 function dispose(){if(disposed)return;unmount();disposed=true;}
 return {mount,unmount,dispose,refresh,startGps:gpsStart,stopGps,
         state:()=>({gpsEnabled,hasMap:viewReady,selectedOrder:selected?.id||null})};
}
root.PD_PILOT_COCKPIT_STAGED={make,pickActive,nextAction,coords};
})(typeof window!=='undefined'?window:globalThis);
