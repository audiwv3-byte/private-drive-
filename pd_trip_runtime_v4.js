/* Draft integration: append after the existing Mini App script, after approval. */
(()=>{
'use strict';
const POLICY='pd-trip-v4-20261028';
const label=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const eur=c=>(Number(c||0)/100).toFixed(2)+' €';
let active=null,dialog=null,body=null,map=null,marker=null,watch=null,watchOrder=null,lastPositionSent=0,polling=false,hubBusy=false;
const button=(text,action)=>{const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=text;b.onclick=async()=>{b.disabled=true;try{await action()}catch(e){message(e.message,true)}finally{b.disabled=false}};return b};
const p=(text,parent=body)=>{const e=document.createElement('p');e.textContent=text;parent.append(e);return e};
const requestTrip=(id,suffix='',data)=>api('/api/trip/'+Number(id)+suffix,data);
function stopPosition(){if(watch!==null)navigator.geolocation.clearWatch(watch);watch=null;watchOrder=null}
function closing(activeTrip){try{if(activeTrip)window.Telegram?.WebApp?.enableClosingConfirmation();else window.Telegram?.WebApp?.disableClosingConfirmation()}catch(_){}}
async function position(id){
 if(watchOrder===id){stopPosition();await refresh();return}
 if(!navigator.geolocation)throw Error(label('Геолокация недоступна','Geolocation is unavailable','Geolokacija nepasiekiama'));
 stopPosition();watchOrder=id;closing(true);
 watch=navigator.geolocation.watchPosition(async pos=>{
  if(watchOrder!==id||document.hidden||Date.now()-lastPositionSent<5000)return;
  lastPositionSent=Date.now();
  try{await requestTrip(id,'/location',{lat:pos.coords.latitude,lon:pos.coords.longitude,accuracy:pos.coords.accuracy})}
  catch(e){stopPosition();message(e.message,true)}
 },e=>{stopPosition();message(label('Нет доступа к геопозиции. Разрешите её в Telegram или браузере.','Location access denied. Allow it in Telegram or your browser.','Vietovės prieiga nesuteikta. Leiskite ją Telegram arba naršyklėje.'),true)},
 {enableHighAccuracy:true,maximumAge:5000,timeout:15000});
 await refresh();
}
function cleanDialog(){if(map)map.remove();map=null;marker=null;dialog=null;body=null;active=null}
window.pdOpenLiveTripV4=async function(id){
 if(dialog){dialog.close();cleanDialog()}
 dialog=pdSimpleDialog(label('Текущая поездка','Current trip','Dabartinė kelionė'));dialog.id='pdTripRuntimeV4';
 body=document.createElement('div');dialog.append(body);active=Number(id);
 dialog.addEventListener('close',cleanDialog,{once:true});
 await refresh();
};
async function action(name){await requestTrip(active,'/action',{action:name});await refresh();if(name==='finish'){stopPosition();closing(false);if(typeof pdCheckTripCompletion==='function')pdCheckTripCompletion()}}
async function offerExtra(){
 const d=pdSimpleDialog(label('Дополнительная услуга','Additional service','Papildoma paslauga'));
 const reason=document.createElement('input');reason.placeholder=label('Остановка или пожелание','Stop or request','Sustojimas ar pageidavimas');reason.maxLength=300;
 const amount=document.createElement('input');amount.type='number';amount.min='0.01';amount.step='0.01';amount.placeholder=label('Сумма в EUR','Amount in EUR','Suma EUR');
 const key=crypto.randomUUID();
 const save=button(label('Предложить пассажиру','Offer to passenger','Pasiūlyti keleiviui'),async()=>{
  const cents=Math.round(Number(amount.value)*100);if(!Number.isFinite(cents)||cents<=0)throw Error(label('Укажите сумму','Enter amount','Įveskite sumą'));
  await requestTrip(active,'/extras',{reason:reason.value,amount_cents:cents,request_key:key});d.close();await refresh();
 });d.append(reason,amount,save);
}
async function refresh(){
 if(!active||!body||polling)return;polling=true;
 try{
  const id=active,r=await requestTrip(id);if(active!==id||!body)return;
  if(map)map.remove();map=null;marker=null;body.replaceChildren();
  p(label('Заказ №','Order #','Užsakymas Nr. ')+id+' · '+r.status);
  const live=['Подтверждена','В пути'].includes(r.status);closing(live);
  if(!live&&watchOrder===id)stopPosition();
  if(r.role==='pilot'&&live){
   body.append(button(watchOrder===id?label('Остановить передачу геопозиции','Stop sharing location','Stabdyti vietovės bendrinimą'):label('Передавать мою геопозицию','Share my location','Bendrinti mano vietovę'),()=>position(id)));
   p(label('Геопозиция обновляется только при открытом приложении и разрешённом доступе. Не закрывайте Mini App до конца поездки.','Location updates require the app to stay open and location permission. Keep the Mini App open until the trip ends.','Vietovė atnaujinama tik atidarius programėlę ir leidus prieigą. Laikykite ją atidarytą iki kelionės pabaigos.'));
  }
  if(live&&Number.isFinite(r.lat)&&Number.isFinite(r.lon)&&window.L){
   const box=document.createElement('div');box.style.cssText='height:240px;margin:14px 0;border-radius:12px';body.append(box);
   map=L.map(box).setView([r.lat,r.lon],15);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(map);
   marker=L.marker([r.lat,r.lon]).addTo(map);L.circle([r.lat,r.lon],{radius:Math.min(r.accuracy||0,1000)}).addTo(map);
   p(r.location_stale?label('Последняя геопозиция устарела — положение сейчас неизвестно.','Location is stale — current position is unknown.','Vietovė pasenusi — dabartinė padėtis nežinoma.'):label('Местоположение пилота · обновлено: ','Pilot location · updated: ','Piloto vietovė · atnaujinta: ')+new Date(r.location_at*1000).toLocaleTimeString());
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
  if(r.role==='pilot'&&r.status==='Подтверждена')body.append(button(r.arrived_at?label('Начать поездку','Start trip','Pradėti kelionę'):label('Прибыл','Arrived','Atvykau'),()=>action(r.arrived_at?'start':'arrive')));
  if(r.role==='pilot'&&live)body.append(button(label('Остановка / дополнительная услуга','Stop / extra service','Sustojimas / papildoma paslauga'),offerExtra));
  for(const extra of r.extras){
   const item=document.createElement('div');item.className='item';p(extra.reason+' · '+eur(extra.amount_cents)+' · '+extra.state,item);
   if(r.role==='passenger'&&extra.state==='proposed')for(const accept of [true,false])item.append(button(accept?label('Согласен с доплатой','Accept extra','Sutinku primokėti'):label('Отклонить','Reject','Atmesti'),async()=>{await requestTrip(id,'/extras/'+extra.id,{accept});await refresh()}));
   body.append(item);
  }
  if(r.role==='pilot'&&r.status==='В пути')body.append(button(label('Поездка завершена','Trip completed','Kelionė baigta'),()=>action('finish')));
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
   if(r.role==='pilot'&&r.card_capture_available&&r.capture&&['authorized','capturing'].includes(r.capture.state))body.append(button(label('Принять заявку и списать стоимость','Accept booking and charge fare','Priimti užsakymą ir nuskaityti kainą'),async()=>{await requestTrip(id,'/accept',{});await refresh()}));
  }
 }catch(e){if(body)p(e.message)}finally{polling=false}
}
async function hubs(){
 if(hubBusy||!initData||!pdRegistered||document.hidden)return;hubBusy=true;
 try{
  const containers=[['step8','/api/orders'],['pdPilotWork','/api/driver/work'],['step13','/api/driver/work']];
  for(const [parentId,path]of containers){
   const parent=document.getElementById(parentId);if(!parent||parent.classList.contains('hidden'))continue;
   let box=document.getElementById('pdTripHubV4-'+parentId);if(!box){box=document.createElement('div');box.id='pdTripHubV4-'+parentId;parent.append(box)}
   const result=await api(path);box.replaceChildren();
   for(const order of result.orders.filter(o=>['Новая','Подтверждена','В пути','Выполнена'].includes(o.status)).slice(0,15))box.append(button(label('Поездка №','Trip #','Kelionė Nr. ')+order.id+' · '+order.status,()=>window.pdOpenLiveTripV4(order.id)));
  }
 }catch(_){/* Existing lists remain usable if the V4 service is unavailable. */}finally{hubBusy=false}
}
setInterval(()=>{if(!document.hidden){refresh();hubs()}},10000);
setInterval(()=>{document.querySelectorAll('[data-wait-start]').forEach(e=>{if(!e.dataset.waitEnd||Number(e.dataset.waitEnd)===0){const elapsed=Math.max(0,Math.floor((Date.now()+Number(e.dataset.serverOffset))/1000)-Number(e.dataset.waitStart));e.textContent=label('Ожидание: ','Waiting: ','Laukimas: ')+Math.floor(elapsed/60)+':'+String(elapsed%60).padStart(2,'0')+label(' · стоимость уточняется сервером',' · server updates the fare',' · kainą atnaujina serveris')}})},1000);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPosition();else{refresh();hubs()}});
window.addEventListener('pagehide',stopPosition);setTimeout(hubs,1500);
})();
