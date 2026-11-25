/* Separate pilot cabinet, private photos and full admin trip details. */
(()=>{
'use strict';
const tr=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const duration=s=>s===null||s===undefined?tr('Не зафиксировано','Not recorded','Neužfiksuota'):Math.floor(s/3600)+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
const stamp=s=>s?new Date(s*1000).toLocaleString(window.PD_LANG||'ru',{timeZone:'Europe/Vilnius'}):'—';
const euro=c=>(Number(c||0)/100).toFixed(2)+' €';
const photoLabels={portrait:tr('Фото пилота','Pilot portrait','Piloto portretas'),license_front:tr('Права — лицевая сторона','Licence — front','Pažymėjimas — priekis'),license_back:tr('Права — обратная сторона','Licence — back','Pažymėjimas — galas'),car_front:tr('Автомобиль — спереди','Car — front','Automobilis — priekis'),car_rear:tr('Автомобиль — сзади','Car — rear','Automobilis — galas'),car_interior:tr('Автомобиль — салон','Car — interior','Automobilis — salonas')};
Object.entries(photoLabels).forEach(([key,value])=>{window.PD_UI[pdDocumentLabels[key]||key]=value});
let tab='map',workRequest=0,pilotMap=null;
function closeMap(){
 if(pilotMap)pilotMap.remove();
 pilotMap=null;
}
function openMap(box,request){
 const mapElement=document.createElement('div');mapElement.id='pdPilotMap';
 mapElement.setAttribute('aria-label',tr('Карта пилота','Pilot map','Piloto žemėlapis'));
 const hint=document.createElement('p');hint.setAttribute('role','status');
 box.append(mapElement,hint);
 const unavailable=tr('Карта не загрузилась. Нажмите «Обновить».','Could not load the map. Select Refresh.','Žemėlapis neįkeltas. Paspauskite „Atnaujinti“.');
 if(!window.L){mapElement.hidden=true;hint.textContent=unavailable;return}
 const map=L.map(mapElement).setView([54.6872,25.2797],13);
 pilotMap=map;
 const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
  maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
 }).addTo(map);
 tiles.on('tileerror',()=>{hint.textContent=unavailable});
 tiles.on('tileload',()=>{if(hint.textContent===unavailable)hint.textContent=''});
 requestAnimationFrame(()=>{if(pilotMap===map)map.invalidateSize()});
 let marker;
 box.append(b(tr('Моё местоположение','My location','Mano buvimo vieta'),()=>{
  const failed=()=>{if(request===workRequest)hint.textContent=tr('Разрешите геолокацию в настройках устройства.','Allow location access in your device settings.','Įrenginio nustatymuose leiskite pasiekti vietovę.')};
  if(!navigator.geolocation){failed();return}
  navigator.geolocation.getCurrentPosition(({coords})=>{
   if(request!==workRequest)return;
   const point=[coords.latitude,coords.longitude];
   if(marker)marker.setLatLng(point);
   else marker=L.circleMarker(point,{radius:8,color:'#fff',weight:2,fillColor:'#218bf3',fillOpacity:1}).addTo(map);
   map.setView(point,16);hint.textContent='';
  },failed,{enableHighAccuracy:true,timeout:12000});
 }));
}
window.pdRenderPilotIdentityCard=function(box,profile,photos){
 const card=document.createElement('div');card.className='pd-pilot-identity';box.append(card);
 for(const side of ['portrait','car_front']){
  if(!photos?.[side])continue;
  const img=document.createElement('img');img.alt=photoLabels[side];img.hidden=true;card.append(img);
  fetch(photos[side],{headers:{'X-Telegram-Init-Data':initData},cache:'no-store'})
   .then(response=>response.ok?response.blob():null).then(blob=>{
    if(!blob||!img.isConnected)return;
    const url=URL.createObjectURL(blob);
    img.onload=()=>{img.hidden=false;URL.revokeObjectURL(url)};
    img.onerror=()=>URL.revokeObjectURL(url);
    img.src=url;
   }).catch(()=>{});
 }
 line(card,tr('Пилот','Pilot','Pilotas'),profile.name);
 line(card,tr('Автомобиль','Vehicle','Automobilis'),[profile.vehicle,profile.vehicle_year].filter(Boolean).join(' · '));
 line(card,tr('Номер автомобиля','Plate','Valstybinis numeris'),profile.plate);
};
function b(label,action){const el=document.createElement('button');el.type='button';el.className='secondary';el.textContent=label;el.onclick=action;return el}
function line(parent,label,value){const p=document.createElement('p');const strong=document.createElement('strong');strong.textContent=label+': ';p.append(strong,document.createTextNode(value===null||value===undefined?'—':String(value)));parent.append(p)}
function buttons(){
 let nav=document.getElementById('pdPilotNavV4');if(nav)return nav;
 nav=document.createElement('nav');nav.id='pdPilotNavV4';nav.className='actions';nav.setAttribute('aria-label',tr('Разделы кабинета пилота','Pilot cabinet sections','Piloto paskyros skyriai'));
 for(const [key,text]of [['map',tr('Карта','Map','Žemėlapis')],['active',tr('Активные заказы','Active orders','Aktyvūs užsakymai')],['history',tr('История поездок','Trip history','Kelionių istorija')],['vehicle',tr('Мой автомобиль','My vehicle','Mano automobilis')],['documents',tr('Документы и фото','Documents and photos','Dokumentai ir nuotraukos')]])nav.append(b(text,()=>{tab=key;pdPilotWork()}));
 const section=document.getElementById('pdPilotWork');section.insertBefore(nav,document.getElementById('pdPilotWorkList'));return nav;
}
pdEnterPilot=function(){
 const user=window.pdOnboardingUser;if(!user||(!pdPilotEnabled&&!user.driver_application))return;
 pdApplyRoleAccess(user,'driver');pdHideOnboarding();document.body.classList.add('admin-home','pd-pilot-cabinet');
 document.querySelectorAll('section[id^="step"]').forEach(x=>x.classList.add('hidden'));
 document.getElementById('pdPilotWork').classList.remove('hidden');document.getElementById('mainNav').classList.add('hidden');document.getElementById('pdPilotBack').classList.add('hidden');
 document.getElementById('pdPilotWorkTitle').textContent=tr('Кабина пилота','Pilot cockpit','Piloto kabina');
 document.getElementById('pdPilotWorkRefresh').textContent=tr('Обновить','Refresh','Atnaujinti');
 const passenger=document.getElementById('pdPilotPassenger');passenger.textContent=tr('Перейти в пассажирский кабинет','Open passenger cabinet','Atidaryti keleivio paskyrą');passenger.classList.toggle('hidden',!user.registered);
 buttons();pdPilotWork();window.scrollTo(0,0);
};
const oldPassenger=pdPilotPassenger;pdPilotPassenger=function(){workRequest++;closeMap();tab='map';document.body.classList.remove('pd-pilot-cabinet');oldPassenger()};
pdPilotWork=async function(refresh=false){
 const request=++workRequest;
 const box=document.getElementById('pdPilotWorkList');closeMap();box.replaceChildren();buttons();
 try{
  if(refresh){
   const user=await api('/api/me');
   if(request!==workRequest)return;
   window.pdOnboardingUser=user;pdPilotEnabled=Boolean(user.pilot_access);pdApplyRoleAccess(user,'driver');
  }
  const application=window.pdOnboardingUser?.driver_application;
  if(!pdPilotEnabled){
   const states={pending:tr('Заявка на проверке. Рабочие заказы будут доступны после одобрения.','Application under review. Work orders unlock after approval.','Paraiška tikrinama. Darbo užsakymai bus prieinami patvirtinus.'),rejected:tr('Заявка отклонена. Можно исправить данные и отправить повторно.','Application rejected. Correct your details and submit again.','Paraiška atmesta. Pataisykite duomenis ir pateikite iš naujo.')};
   line(box,tr('Статус заявки','Application status','Paraiškos būsena'),states[application?.status]||tr('Нет допуска к заказам','Work access not granted','Prieiga prie užsakymų nesuteikta'));
   if(tab==='active'||tab==='history')return;
  }
  if(tab==='map'){openMap(box,request);return}
  if(tab==='vehicle'||tab==='documents'){
   if(!application){line(box,tr('Профиль','Profile','Profilis'),tr('Данные заявки отсутствуют','No application data','Paraiškos duomenų nėra'));return}
   if(tab==='vehicle'){
    const photos=Object.fromEntries(['portrait','car_front'].filter(side=>(application.document_sides||[]).includes(side))
     .map(side=>[side,'/api/driver/documents/'+Number(window.pdOnboardingUser.id)+'/'+side]));
    window.pdRenderPilotIdentityCard(box,application,photos);
   }else{
    for(const [side,title]of Object.entries(photoLabels)){
     if((application.document_sides||[]).includes(side))box.append(b(title,()=>pdPreviewDocument(side,window.pdOnboardingUser.id)));
     else line(box,title,tr('Не загружено','Not uploaded','Neįkelta'));
    }
   }
   line(box,tr('Изменение данных','Update details','Duomenų keitimas'),tr('Повторная отправка заявки возвращает её на проверку администратора.','Resubmitting returns the application to admin review.','Pakartotinai pateikta paraiška vėl tikrinama administratoriaus.'));
   box.append(b(tr('Обновить данные и фотографии','Update details and photos','Atnaujinti duomenis ir nuotraukas'),()=>{closeMap();pdShowOnboarding('driver')}));return;
  }
  const result=await api('/api/driver/work');if(request!==workRequest)return;const rows=result.orders.filter(o=>tab==='history'?['Выполнена','Отменена'].includes(o.status):!['Выполнена','Отменена'].includes(o.status));
  if(!rows.length){line(box,tr('Поездки','Trips','Kelionės'),tr('В этом разделе поездок пока нет','No trips in this section','Šiame skyriuje kelionių nėra'));return}
  for(const order of rows){
   const article=document.createElement('article');article.className='item';const h=document.createElement('h3');h.textContent='№'+order.id+' · '+pdL(order.status);article.append(h);
   line(article,tr('Маршрут','Route','Maršrutas'),[order.origin,order.stop_address,order.destination].filter(Boolean).join(' → '));
   line(article,tr('Дата и время подачи','Pickup date and time','Paėmimo data ir laikas'),order.trip_date+' '+order.trip_time);
   line(article,tr('Пассажир','Passenger','Keleivis'),order.customer?.name);
   if(order.customer?.phone){const a=document.createElement('a');a.href='tel:'+order.customer.phone.replace(/[^+0-9]/g,'');a.textContent=order.customer.phone;article.append(a)}
   line(article,tr('Пожелания','Requests','Pageidavimai'),order.details||'—');
   line(article,tr('Стоимость','Fare','Kaina'),order.final_cents!==null&&order.final_cents!==undefined?euro(order.final_cents):order.price+' €');
   line(article,tr('Оплата','Payment','Mokėjimas'),order.payment_status);
   line(article,tr('Время движения','Driving time','Važiavimo laikas'),duration(order.drive_seconds));
   article.append(b(tr('Открыть рабочую поездку','Open work trip','Atidaryti darbo kelionę'),()=>pdOpenLiveTripV4(order.id)));box.append(article);
  }
 }catch(e){if(request===workRequest)line(box,tr('Ошибка','Error','Klaida'),e.message)}
};
window.pdOpenAdminTripV4=async function(id){
 if(!admin)return;
 const d=pdSimpleDialog(tr('Полная информация о поездке №','Full trip details #','Visa kelionės informacija Nr. ')+Number(id));const content=document.createElement('div');d.append(content);
 try{
  const r=await api('/api/admin/trip/'+Number(id)),o=r.order;
  const sections=[
   [tr('Поездка','Trip','Kelionė'),[
    [tr('Статус','Status','Būsena'),o.status],[tr('Маршрут','Route','Maršrutas'),[o.origin,o.stop_address,o.destination].filter(Boolean).join(' → ')],
    [tr('Подача','Pickup','Paėmimas'),[o.trip_date,o.trip_time].join(' ')],[tr('Пассажиров','Passengers','Keleivių'),o.passengers],[tr('Багаж','Luggage','Bagažas'),o.luggage],[tr('Пожелания','Requests','Pageidavimai'),o.details],
    [tr('Расстояние, км','Distance, km','Atstumas, km'),o.distance_km],[tr('Прогноз времени, мин','Estimated time, min','Numatoma trukmė, min'),o.duration_min]]],
   [tr('Фактическое время','Actual timing','Faktinis laikas'),[
    [tr('Пилот прибыл','Pilot arrived','Pilotas atvyko'),stamp(r.arrived_at)],[tr('Начало движения','Driving started','Važiavimo pradžia'),stamp(r.started_at)],[tr('Завершение','Completed','Baigta'),stamp(r.ended_at)],
    [tr('Время движения','Driving time','Važiavimo laikas'),duration(r.drive_seconds)],[tr('Ожидание','Waiting','Laukimas'),duration(r.waiting_seconds)],[tr('Всего с момента прибытия','Total since arrival','Iš viso nuo atvykimo'),duration(r.total_service_seconds)]]],
   [tr('Стоимость и оплата','Fare and payment','Kaina ir mokėjimas'),[
    [tr('Основная цена','Base fare','Pagrindinė kaina'),euro(r.base_cents)],[tr('Ожидание','Waiting','Laukimas'),euro(r.wait_cents)],[tr('Итог','Final fare','Galutinė kaina'),r.final_cents===null||r.final_cents===undefined?tr('Ещё не зафиксирован','Not finalized','Dar neužfiksuota'):euro(r.final_cents)],
    [tr('Способ оплаты','Payment method','Mokėjimo būdas'),o.payment_method],[tr('Статус оплаты','Payment status','Mokėjimo būsena'),o.payment_status],[tr('Статус списания','Capture state','Nuskaitymo būsena'),r.capture?.state||'—'],[tr('Возврат','Refund','Grąžinimas'),r.cancellation?r.cancellation.state+' · '+euro(r.cancellation.refund_cents):'—']]]
  ];
  for(const[title,fields]of sections){const h=document.createElement('h3');h.textContent=title;content.append(h);for(const[label,value]of fields)line(content,label,value)}
  for(const[key,title]of [['customer',tr('Пассажир','Passenger','Keleivis')],['pilot',tr('Назначенный пилот','Assigned pilot','Priskirtas pilotas')]]){
   const item=r[key];const h=document.createElement('h3');h.textContent=title;content.append(h);
   if(!item){line(content,title,'—');continue}
   line(content,tr('Имя','Name','Vardas'),item.name);line(content,'Telegram ID',item.telegram_id);
   if(item.phone){const a=document.createElement('a');a.href='tel:'+String(item.phone).replace(/[^+0-9]/g,'');a.textContent=item.phone;content.append(a)}
   if(key==='pilot'){
    line(content,tr('Автомобиль','Vehicle','Automobilis'),[item.vehicle,item.vehicle_year,item.plate].filter(Boolean).join(' · '));
    for(const side of item.document_sides||[])content.append(b(photoLabels[side]||pdDocumentLabels[side]||side,()=>pdPreviewDocument(side,item.telegram_id)));
   }
  }
  const extraHeading=document.createElement('h3');extraHeading.textContent=tr('Остановки и доплаты','Stops and extras','Sustojimai ir priemokos');content.append(extraHeading);
  for(const extra of r.extras)line(content,extra.reason,euro(extra.amount_cents)+' · '+extra.state);
  const eventLabels={arrived:tr('Пилот прибыл','Pilot arrived','Pilotas atvyko'),started:tr('Движение началось','Driving started','Važiavimas prasidėjo'),completed:tr('Поездка окончена','Trip completed','Kelionė baigta'),waiting_tariff_accepted:tr('Пассажир подтвердил тариф ожидания','Passenger accepted waiting tariff','Keleivis patvirtino laukimo tarifą'),extra_proposed:tr('Предложена доплата','Extra proposed','Pasiūlyta priemoka'),extra_accepted:tr('Доплата принята','Extra accepted','Priemoka priimta'),extra_rejected:tr('Доплата отклонена','Extra rejected','Priemoka atmesta')};
  const h=document.createElement('h3');h.textContent=tr('Хронология','Timeline','Chronologija');content.append(h);for(const ev of r.events)line(content,stamp(ev.created_at),(eventLabels[ev.event]||ev.event)+' · ID '+ev.actor_id);
 }catch(e){line(content,tr('Ошибка','Error','Klaida'),e.message)}
};
const originalOnboarding=pdOnboardingStart;
pdOnboardingStart=function(user){originalOnboarding(user);const source=new URLSearchParams(window.location.search).get('start')||window.Telegram?.WebApp?.initDataUnsafe?.start_param;if(source==='driver_taxi_lt'&&user&&!user.registered&&!user.driver_application&&!user.pilot_access)pdStartDriverRegistration()};
if(window.pdOnboardingUser?.driver_application&&!window.pdOnboardingUser.admin)pdEnterPilot();
else if(window.pdOnboardingUser&&(new URLSearchParams(window.location.search).get('start')==='driver_taxi_lt'))pdStartDriverRegistration();
})();
