/* Draft integration: append after the existing Mini App script, after approval. */
(()=>{
'use strict';
const POLICY='pd-trip-v4-20261028';
const label=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const eur=c=>(Number(c||0)/100).toFixed(2)+' €';
let active=null,dialog=null,body=null,map=null,marker=null,watch=null,watchOrder=null,lastPositionSent=0,polling=false,hubBusy=false,lastRender=null,locationCircle=null,locationText=null;
const button=(text,action)=>{const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=text;b.onclick=async()=>{b.disabled=true;try{await action()}catch(e){if(body){const notice=p(e.message);notice.setAttribute('role','alert')}message(e.message,true)}finally{b.disabled=false}};return b};
const p=(text,parent=body)=>{const e=document.createElement('p');e.textContent=text;parent.append(e);return e};
const requestTrip=(id,suffix='',data)=>api('/api/trip/'+Number(id)+suffix,data);
function stopPosition(forget=false){if(watch!==null)navigator.geolocation.clearWatch(watch);watch=null;watchOrder=null;if(forget)rememberTracking(null)}
function closing(activeTrip){try{if(activeTrip||watchOrder!==null)window.Telegram?.WebApp?.enableClosingConfirmation();else window.Telegram?.WebApp?.disableClosingConfirmation()}catch(_){}}
const trackingKey=()=> 'pdPickupTrackingV4:'+String(window.pdOnboardingUser?.id||'');
let geoBlocked=false,trackingSyncBusy=false;
function rememberTracking(id){try{if(id)localStorage.setItem(trackingKey(),String(id));else localStorage.removeItem(trackingKey())}catch(_){}}
function rememberedTracking(){try{return Number(localStorage.getItem(trackingKey()))||null}catch(_){return null}}
function firstPosition(){return new Promise((resolve,reject)=>{if(!navigator.geolocation){reject(Error(label('Геолокация недоступна','Geolocation unavailable','Geolokacija nepasiekiama')));return}navigator.geolocation.getCurrentPosition(resolve,()=>reject(Error(label('Для выезда к пассажиру разрешите геолокацию в Telegram или браузере.','Allow location access in Telegram or your browser before driving to pickup.','Prieš vykdami pas keleivį leiskite vietovės prieigą Telegram arba naršyklėje.'))),{enableHighAccuracy:true,maximumAge:0,timeout:15000})})}
async function position(id){
 if(watchOrder===id&&watch!==null)return;
 if(!navigator.geolocation)throw Error(label('Геолокация недоступна','Geolocation unavailable','Geolokacija nepasiekiama'));
 stopPosition();watchOrder=id;lastPositionSent=0;geoBlocked=false;closing(true);rememberTracking(id);
 watch=navigator.geolocation.watchPosition(async pos=>{
  if(watchOrder!==id||document.hidden||Date.now()-lastPositionSent<5000)return;
  lastPositionSent=Date.now();
  try{await requestTrip(id,'/location',{lat:pos.coords.latitude,lon:pos.coords.longitude,accuracy:pos.coords.accuracy})}
  catch(e){stopPosition();message(e.message,true)}
 },e=>{geoBlocked=e.code===1;stopPosition();message(label('Передача геопозиции прервана. Проверьте разрешение и держите приложение открытым.','Location sharing interrupted. Check permission and keep the app open.','Vietovės bendrinimas nutrūko. Patikrinkite leidimą ir laikykite programėlę atidarytą.'),true);refresh()},
 {enableHighAccuracy:true,maximumAge:5000,timeout:15000});
}
async function beginDeparture(id){
 const fix=await firstPosition();await requestTrip(id,'/depart',{lat:fix.coords.latitude,lon:fix.coords.longitude,accuracy:fix.coords.accuracy});await position(id);await refresh();
}
window.pdBeginPickupV4=beginDeparture;
let startRideBusy=false;
window.pdStartRideV7=async function(id,recover=false){
 if(startRideBusy)return;startRideBusy=true;
 try{
  const work=await api('/api/driver/work');
  const order=(work.orders||[]).find(o=>Number(o.id)===Number(id));
  if(!order)throw Error(label('Заказ не назначен вам или доступ пилота изменился. Обновите кабинет.','The order is not assigned to you or pilot access changed. Refresh the cabinet.','Užsakymas jums nepriskirtas arba piloto prieiga pasikeitė. Atnaujinkite paskyrą.'));
  if(order.payment_status!=='Оплачено')throw Error(label('Заказ подтверждён, но оплата ещё не подтверждена. Статус оплаты: ','The booking is confirmed, but payment is not confirmed. Payment status: ','Užsakymas patvirtintas, tačiau mokėjimas dar nepatvirtintas. Mokėjimo būsena: ')+pdL(order.payment_status||'Не оплачено')+label('. Диспетчер должен отдельно подтвердить фактическое поступление денег.','. The dispatcher must separately confirm receipt of funds.','. Dispečeris turi atskirai patvirtinti pinigų gavimą.'));
  const fix=await firstPosition(),coords={lat:fix.coords.latitude,lon:fix.coords.longitude,accuracy:fix.coords.accuracy};
  await requestTrip(id,'/action',{action:recover?'recover_start':'start',...coords});
  await position(id);await requestTrip(id,'/location',coords);await refresh();
 }finally{startRideBusy=false}
};

async function syncTracking(){
 if(trackingSyncBusy||document.hidden||!initData||geoBlocked)return;
 const id=watchOrder||rememberedTracking();if(!id)return;trackingSyncBusy=true;
 try{const r=await requestTrip(id);if(r.role!=='pilot'||!r.departed_at||!['Подтверждена','В пути'].includes(r.status)){stopPosition(true);return}if(watchOrder!==id||watch===null)await position(id)}catch(_){stopPosition()}finally{trackingSyncBusy=false}
}

function cleanDialog(){stopPosition();closing(false);if(map)map.remove();map=null;marker=null;locationCircle=null;locationText=null;lastRender=null;dialog=null;body=null;active=null}
window.pdOpenLiveTripV4=async function(id){
 if(dialog){dialog.close();cleanDialog()}
 dialog=pdSimpleDialog(label('Текущая поездка','Current trip','Dabartinė kelionė'));dialog.id='pdTripRuntimeV4';
 body=document.createElement('div');dialog.append(body);active=Number(id);
 dialog.addEventListener('close',cleanDialog,{once:true});
 await refresh();
};
async function action(name){await requestTrip(active,'/action',{action:name});await refresh();if(name==='finish'){stopPosition(true);closing(false);if(typeof pdCheckTripCompletion==='function')pdCheckTripCompletion()}}
async function refresh(){
 if(!active||!body||polling)return;polling=true;
 try{
  const id=active,r=await requestTrip(id);if(active!==id||!body)return;
  const hasLocation=['Подтверждена','В пути'].includes(r.status)&&Number.isFinite(r.lat)&&Number.isFinite(r.lon)&&Boolean(window.L);
  const signature=JSON.stringify([watchOrder,hasLocation,Object.fromEntries(Object.entries(r).filter(([k])=>!['server_now','lat','lon','accuracy','location_at','location_stale'].includes(k)))]);
  const updateLocation=()=>{if(!map||!marker||!hasLocation)return;const point=[r.lat,r.lon];marker.setLatLng(point);if(locationCircle){locationCircle.setLatLng(point);locationCircle.setRadius(Math.min(r.accuracy||0,1000))}if(locationText)locationText.textContent=r.location_stale?label('Последняя геопозиция устарела — положение сейчас неизвестно.','Location is stale — current position is unknown.','Vietovė pasenusi — dabartinė padėtis nežinoma.'):label('Местоположение пилота · обновлено: ','Pilot location · updated: ','Piloto vietovė · atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString()};
  if(signature===lastRender){updateLocation();return}
  lastRender=null;
  if(map)map.remove();map=null;marker=null;locationCircle=null;locationText=null;body.replaceChildren();
  p(label('Заказ №','Order #','Užsakymas Nr. ')+id+' · '+r.status);
  const live=['Подтверждена','В пути'].includes(r.status);closing(live);
  if(!live&&(watchOrder===id||rememberedTracking()===id))stopPosition(true);
  if(r.role==='pilot'&&live){
   if(r.departed_at){
    p(watchOrder===id?label('📍 Геопозиция передаётся пассажиру','📍 Sharing location with passenger','📍 Vietovė bendrinama su keleiviu'):label('⚠ Передача геопозиции прервана','⚠ Location sharing interrupted','⚠ Vietovės bendrinimas nutrūko'));
    if(watchOrder!==id)body.append(button(label('Восстановить геолокацию','Restore location sharing','Atkurti vietovės bendrinimą'),async()=>{geoBlocked=false;await firstPosition();await position(id);await refresh()}));
   }
   p(label('Не закрывайте Mini App и не блокируйте экран до завершения поездки. При потере GPS пассажир увидит, что координаты устарели.','Keep the Mini App open and screen unlocked until the trip ends. GPS loss is shown to the passenger.','Laikykite programėlę atidarytą ir ekraną atrakintą iki kelionės pabaigos. GPS ryšio praradimas rodomas keleiviui.'));
  }
  if(live&&Number.isFinite(r.lat)&&Number.isFinite(r.lon)&&window.L){
   const box=document.createElement('div');box.style.cssText='height:240px;margin:14px 0;border-radius:12px';body.append(box);
   map=L.map(box).setView([r.lat,r.lon],15);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(map);
   marker=L.marker([r.lat,r.lon]).addTo(map);locationCircle=L.circle([r.lat,r.lon],{radius:Math.min(r.accuracy||0,1000)}).addTo(map);
   locationText=p(r.location_stale?label('Последняя геопозиция устарела — положение сейчас неизвестно.','Location is stale — current position is unknown.','Vietovė pasenusi — dabartinė padėtis nežinoma.'):label('Местоположение пилота · обновлено: ','Pilot location · updated: ','Piloto vietovė · atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString());
  }else if(live){p(label('Ожидаем геопозицию пилота.','Waiting for pilot location.','Laukiama piloto vietovės.'))}
  if(r.role==='passenger'&&!r.wait_accepted_at&&['Новая','Подтверждена'].includes(r.status)){
   p(label('Ожидание: 5 минут бесплатно, далее 0,25 € за каждую начатую минуту. До подтверждения тарифа платное ожидание не начисляется.','Waiting: 5 minutes free, then €0.25 per started minute. No paid waiting is charged before you accept.','Laukimas: 5 minutės nemokamai, vėliau 0,25 € už kiekvieną pradėtą minutę. Mokestis neskaičiuojamas iki patvirtinimo.'));
   body.append(button(label('Подтвердить тариф ожидания','Accept waiting tariff','Patvirtinti laukimo tarifą'),async()=>{await requestTrip(id,'/waiting-consent',{accept:true,policy:POLICY});await refresh()}));
  }
  if(r.arrived_at){
   const end=r.started_at||r.server_now,elapsed=Math.max(0,end-r.arrived_at);
   const time=document.createElement('p');time.dataset.waitStart=r.arrived_at;time.dataset.waitEnd=r.started_at||0;time.dataset.serverOffset=r.server_now*1000-Date.now();body.append(time);
   time.textContent=label('Ожидание: ','Waiting: ','Laukimas: ')+Math.floor(elapsed/60)+':'+String(elapsed%60).padStart(2,'0')+' · '+eur(r.wait_cents);
  }
  if(r.role==='pilot'&&r.status==='Подтверждена'){
   if(!r.departed_at)body.append(button(label('В пути к пассажиру','On my way to pickup','Vykstu pas keleivį'),()=>beginDeparture(id)));
   else body.append(button(r.arrived_at?label('В путь','Start trip','Pradėti kelionę'):label('Прибыл','Arrived','Atvykau'),()=>r.arrived_at?window.pdStartRideV7(id):action('arrive')));
  }
  if(r.role==='pilot'&&r.started_at&&!r.ended_at)body.append(button(r.stop_started_at?label('Продолжить поездку','Resume trip','Tęsti kelionę'):label('Остановка','Stop','Sustojimas'),()=>action(r.stop_started_at?'stop_end':'stop_start')));
  if(r.role==='passenger'&&live&&!r.stop_accepted_at){p(label('Остановка: 0,25 € за каждую начатую минуту с первой минуты.','Stops: €0.25 per started minute from the first minute.','Sustojimas: 0,25 € už kiekvieną pradėtą minutę nuo pirmos minutės.'));body.append(button(label('Подтвердить тариф остановки','Accept stop tariff','Patvirtinti sustojimo tarifą'),async()=>{await requestTrip(id,'/stop-consent',{accept:true,policy:'pd-stop-v7-20261029'});await refresh()}))}
  if(r.started_at){p(label('Время поездки: ','Trip time: ','Kelionės laikas: ')+Math.floor(r.drive_seconds/60)+' min · '+Number(r.trip_distance_km||0).toFixed(2)+' km');p(label('Остановки: ','Stops: ','Sustojimai: ')+Math.floor((r.stop_elapsed_seconds||0)/60)+' min · '+eur(r.stop_total_cents))}
  for(const extra of r.extras){
   const item=document.createElement('div');item.className='item';p(extra.reason+' · '+eur(extra.amount_cents)+' · '+extra.state,item);
   if(r.role==='passenger'&&extra.state==='proposed')for(const accept of [true,false])item.append(button(accept?label('Согласен с доплатой','Accept extra','Sutinku primokėti'):label('Отклонить','Reject','Atmesti'),async()=>{await requestTrip(id,'/extras/'+extra.id,{accept});await refresh()}));
   body.append(item);
  }
  if(r.role==='pilot'&&r.status==='В пути'&&!r.started_at){p(label('В старой поездке время начала не записано. Нажмите «В путь»: учёт начнётся с текущего момента.','This older trip has no recorded start. Press Start trip to begin metering now.','Šioje ankstesnėje kelionėje nėra pradžios laiko. Paspauskite Pradėti kelionę: apskaita prasidės dabar.'));body.append(button(label('В путь','Start trip','Pradėti kelionę'),()=>window.pdStartRideV7(id,true)))}
  if(r.role==='pilot'&&r.status==='В пути'&&r.started_at)body.append(button(label('Завершить поездку','Finish trip','Baigti kelionę'),()=>action('finish')));
  if(r.final_cents!==null&&r.final_cents!==undefined){
   p(label('Итоговая стоимость: ','Final fare: ','Galutinė kaina: ')+eur(r.final_cents));
   p(label('Основная цена: ','Base fare: ','Pagrindinė kaina: ')+eur(r.base_cents)+' · '+label('Ожидание: ','Waiting: ','Laukimas: ')+eur(r.wait_cents));
   p(label('Доплаты показаны отдельно и не считаются автоматически списанными.','Extras are listed separately and are not automatically marked as paid.','Priemokos rodomos atskirai ir nelaikomos automatiškai sumokėtomis.'));
  }
  if(r.status==='Новая'){
   if(r.role==='passenger'&&r.card_capture_available&&!r.capture){p(label('Подтвердите карту. Рассчитанная сумма будет списана, когда пилот примет заявку. До принятия возможно временное удержание банком.','Confirm your card. The calculated fare is charged when the pilot accepts. Your bank may show an authorization hold beforehand.','Patvirtinkite kortelę. Apskaičiuota suma nuskaitoma pilotui priėmus užsakymą. Iki tol bankas gali rezervuoti sumą.'));
    body.append(button(label('Подтвердить карту и сумму','Confirm card and amount','Patvirtinti kortelę ir sumą'),async()=>{const result=await requestTrip(id,'/authorize',{accept:true,policy:POLICY});window.Telegram?.WebApp?.openLink?window.Telegram.WebApp.openLink(result.url):window.open(result.url,'_blank','noopener')}));
   }
   if(r.capture)p(label('Статус оплаты: ','Payment state: ','Mokėjimo būsena: ')+r.capture.state);
   if(r.role==='admin'&&r.card_capture_available&&r.capture&&['authorized','capturing'].includes(r.capture.state))body.append(button(label('Подтвердить заказ и списать стоимость','Accept booking and charge fare','Priimti užsakymą ir nuskaityti kainą'),async()=>{await requestTrip(id,'/accept',{});await refresh()}));
  }
  lastRender=signature;
 }catch(e){if(body&&body.dataset.refreshError!==e.message){p(e.message);body.dataset.refreshError=e.message}}finally{polling=false}
}
const passengerMaps=new Map();
async function passengerTracking(parent,parentId,orders){
 let host=document.getElementById('pdDriverMapInline-'+parentId);if(!host){host=document.createElement('div');host.id='pdDriverMapInline-'+parentId;const anchor=parentId==='step11'?document.getElementById('pdbFeedback'):document.getElementById('orders');if(anchor&&parent.contains(anchor)){if(parentId==='step11')anchor.after(host);else anchor.before(host)}else parent.prepend(host)}
 const activeOrders=orders.filter(o=>['Подтверждена','В пути'].includes(o.status)).slice(0,5),keep=new Set();
 const states=await Promise.all(activeOrders.map(async o=>{try{return [o,await requestTrip(o.id)]}catch(_){return [o,null]}}));
 for(const[o,r]of states){const key=parentId+':'+o.id;let entry=passengerMaps.get(key);
  if(!r){if(entry){keep.add(key);entry.status.textContent=label('Нет связи с сервером. Показана последняя известная точка.','No server connection. Showing last known location.','Nėra ryšio su serveriu. Rodoma paskutinė žinoma vieta.')}continue}
  if(!r.departed_at||!['Подтверждена','В пути'].includes(r.status))continue;keep.add(key);
  if(!entry){const card=document.createElement('section');card.className='item';const title=document.createElement('h3');title.textContent='🚘 '+label('Ваш пилот · заказ №','Your pilot · order #','Jūsų pilotas · užsakymas Nr. ')+o.id;const status=document.createElement('p'),canvas=document.createElement('div');canvas.style.cssText='height:260px;border-radius:12px;margin:12px 0';card.append(title,status,canvas,button(label('Открыть поездку','Open trip','Atidaryti kelionę'),()=>window.pdOpenLiveTripV4(o.id)));host.append(card);entry={card,status,canvas,map:null,marker:null};passengerMaps.set(key,entry)}
  entry.status.textContent=r.location_stale?label('⚠ Координаты устарели. Текущее положение пилота неизвестно.','⚠ Location is stale. The pilot’s current position is unknown.','⚠ Vietovė pasenusi. Dabartinė piloto padėtis nežinoma.'):label('Пилот в пути к вам · обновлено: ','Pilot heading to you · updated: ','Pilotas vyksta pas jus · atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString();
  if(r.arrived_at&&!r.location_stale)entry.status.textContent=label('Машина прибыла · геопозиция обновлена: ','Car arrived · location updated: ','Automobilis atvyko · vietovė atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString();
  if(r.status==='В пути'&&!r.location_stale)entry.status.textContent=label('Поездка идёт · геопозиция обновлена: ','Trip in progress · location updated: ','Kelionė vyksta · vietovė atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString();
  if(Number.isFinite(r.lat)&&Number.isFinite(r.lon)&&window.L){const point=[r.lat,r.lon];if(!entry.map){entry.map=L.map(entry.canvas).setView(point,15);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(entry.map);entry.marker=L.marker(point,{icon:L.divIcon({html:'<span style="font-size:28px">🚘</span>',className:'pd-car-map-marker',iconSize:[32,32],iconAnchor:[16,16]})}).addTo(entry.map)}else{entry.marker.setLatLng(point);if(!entry.map.getBounds().contains(point))entry.map.panTo(point)}entry.marker.setOpacity(r.location_stale?0.45:1);setTimeout(()=>entry.map?.invalidateSize(),0)}
 }
 for(const[key,entry]of passengerMaps){if(key.startsWith(parentId+':')&&!keep.has(key)){entry.map?.remove();entry.card.remove();passengerMaps.delete(key)}}
}
async function hubs(){
 if(hubBusy||!initData||!pdRegistered||document.hidden)return;hubBusy=true;
 try{
  const containers=[['step11','/api/orders'],['step8','/api/orders'],['pdPilotWork','/api/driver/work'],['step13','/api/driver/work']];
  for(const [parentId,path]of containers){
   const parent=document.getElementById(parentId);if(!parent||parent.classList.contains('hidden'))continue;
   let box=document.getElementById('pdTripHubV4-'+parentId);if(!box){box=document.createElement('div');box.id='pdTripHubV4-'+parentId;parent.append(box)}
   const result=await api(path);if(parent.classList.contains('hidden'))continue;
   if(path==='/api/orders')await passengerTracking(parent,parentId,result.orders);if(parentId==='step11')continue;
   const orders=result.orders.filter(o=>['Новая','Подтверждена','В пути','Выполнена'].includes(o.status)).slice(0,15),signature=JSON.stringify(orders.map(o=>[o.id,o.status]));
   if(box.dataset.renderSignature===signature)continue;box.replaceChildren();box.dataset.renderSignature=signature;
   for(const order of orders)box.append(button(label('Поездка №','Trip #','Kelionė Nr. ')+order.id+' · '+order.status,()=>window.pdOpenLiveTripV4(order.id)));
  }
 }catch(_){/* Existing lists remain usable if the V4 service is unavailable. */}finally{hubBusy=false}
}
setInterval(()=>{if(!document.hidden){refresh();hubs()}},10000);
setInterval(()=>{document.querySelectorAll('[data-wait-start]').forEach(e=>{if(!e.dataset.waitEnd||Number(e.dataset.waitEnd)===0){const elapsed=Math.max(0,Math.floor((Date.now()+Number(e.dataset.serverOffset))/1000)-Number(e.dataset.waitStart));e.textContent=label('Ожидание: ','Waiting: ','Laukimas: ')+Math.floor(elapsed/60)+':'+String(elapsed%60).padStart(2,'0')+label(' · стоимость уточняется сервером',' · server updates the fare',' · kainą atnaujina serveris')}})},1000);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPosition();else{syncTracking();refresh();hubs()}});
window.addEventListener('pagehide',()=>stopPosition());setTimeout(()=>{hubs();syncTracking()},1500);setInterval(syncTracking,10000);
})();
