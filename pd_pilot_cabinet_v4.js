/* Separate pilot cabinet, private photos and full admin trip details. */
(()=>{
'use strict';
const tr=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const duration=s=>s===null||s===undefined?tr('Не зафиксировано','Not recorded','Neužfiksuota'):Math.floor(s/3600)+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
const stamp=s=>s?new Date(s*1000).toLocaleString(window.PD_LANG||'ru',{timeZone:'Europe/Vilnius'}):'—';
const euro=c=>(Number(c||0)/100).toFixed(2)+' €';
const photoLabels={license_front:tr('Права — лицевая сторона','Licence — front','Pažymėjimas — priekis'),license_back:tr('Права — обратная сторона','Licence — back','Pažymėjimas — galas'),car_front:tr('Автомобиль — спереди','Car — front','Automobilis — priekis'),car_rear:tr('Автомобиль — сзади','Car — rear','Automobilis — galas'),car_interior:tr('Автомобиль — салон','Car — interior','Automobilis — salonas')};
Object.assign(photoLabels,{registration_front:tr('Техпаспорт — лицевая сторона','Vehicle registration — front','Registracijos liudijimas — priekis'),registration_back:tr('Техпаспорт — обратная сторона','Vehicle registration — back','Registracijos liudijimas — galas'),ltsa:tr('Регистрация LTSA','LTSA registration','LTSA registracija'),activity:tr('Индивидуальная деятельность','Individual activity','Individuali veikla'),insurance:tr('Страховка','Insurance','Draudimas'),portrait:tr('Личное фото пилота','Pilot portrait','Piloto portretas')});
Object.entries(photoLabels).forEach(([key,value])=>{window.PD_UI[pdDocumentLabels[key]||key]=value});
let tab='active',busy=false;
function b(label,action){const el=document.createElement('button');el.type='button';el.className='secondary';el.textContent=label;el.onclick=action;return el}
function line(parent,label,value){const p=document.createElement('p');const strong=document.createElement('strong');strong.textContent=label+': ';p.append(strong,document.createTextNode(value===null||value===undefined?'—':String(value)));parent.append(p)}
let pilotCardPhotoURL=null,pilotCardVersion=0;
function pilotCard(application,uid){
 const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node};
 const card=el('article',undefined,'pd-designed-pilot');card.id='pdOwnPilotCardV4';
 const head=el('header',undefined,'pd-designed-pilot-head'),logo=el('img');logo.src='/assets/private-drive-official-logo.jpeg';logo.alt='PRIVATE DRIVE';const brand=el('div');brand.append(el('strong','PRIVATE DRIVE'),el('small',tr('КАРТОЧКА ПИЛОТА','PILOT CARD','PILOTO KORTELĖ')));head.append(logo,brand);card.append(head);
 const grid=el('div',undefined,'pd-designed-pilot-grid'),media=el('div',undefined,'pd-designed-car-photo');media.append(el('p',tr('Загружаем фото автомобиля…','Loading vehicle photo…','Įkeliama automobilio nuotrauka…')));
 const info=el('section',undefined,'pd-designed-pilot-info');info.append(el('h3',tr('Пилот','Pilot','Pilotas')),el('h2',application.name||'—'),el('h3',tr('Автомобиль','Vehicle','Automobilis')),el('strong',[application.vehicle,application.vehicle_year].filter(Boolean).join(' · ')||'—'));
 const plate=el('div',application.plate||'—','pd-designed-plate');plate.setAttribute('aria-label',tr('Номер автомобиля: ','Vehicle plate: ','Valstybinis numeris: ')+(application.plate||'—'));info.append(plate);
 if(application.phone){const phone=el('a','☎ '+application.phone);phone.href='tel:'+application.phone.replace(/[^+0-9]/g,'');info.append(phone)}
 grid.append(media,info);card.append(grid,el('footer',tr('Трансферы в аэропорт · Поездки по Литве и Европе','Airport transfers · Rides in Lithuania and Europe','Pervežimai į oro uostą · Kelionės Lietuvoje ir Europoje'),'pd-designed-pilot-footer'));
 const version=pilotCardVersion;
 if((application.document_sides||[]).includes('car_front'))pdDocumentURL(uid,'car_front').then(url=>{if(version!==pilotCardVersion||!card.isConnected){URL.revokeObjectURL(url);return}pilotCardPhotoURL=url;const image=el('img');image.src=url;image.alt=tr('Автомобиль пилота — вид спереди','Pilot vehicle — front view','Piloto automobilis — vaizdas iš priekio');media.replaceChildren(image)}).catch(()=>{if(version===pilotCardVersion&&card.isConnected)media.replaceChildren(el('p',tr('Фото автомобиля временно недоступно','Vehicle photo temporarily unavailable','Automobilio nuotrauka laikinai nepasiekiama')))});
 else media.replaceChildren(el('p',tr('Добавьте фото автомобиля спереди','Add a front photo of the vehicle','Pridėkite automobilio priekio nuotrauką')));
 return card;
}
function photoPicker(side,title,loaded){
 const label=document.createElement('label');label.className='secondary pd-pilot-photo-picker';
 label.style.cssText='position:relative;display:block;overflow:hidden;cursor:pointer;margin:10px 0;padding:14px;border:1px solid #d9b76b;border-radius:12px;text-align:center';
 const caption=(loaded?tr('Заменить фото','Replace photo','Pakeisti nuotrauką'):tr('Добавить фото','Add photo','Pridėti nuotrauką'))+' · '+title;
 const text=document.createElement('span');text.textContent=caption;label.append(text);
 const input=document.createElement('input');input.type='file';input.accept='image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif';input.id='pdPilotReplace_'+side;input.setAttribute('aria-label',caption);
 input.style.cssText='position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;margin:0';
 input.addEventListener('focus',()=>{label.style.outline='2px solid #f0ce87'});input.addEventListener('blur',()=>{label.style.outline=''});
 input.addEventListener('change',()=>window.pdQueuePilotDocument(side,input));
 if(window.pdPhotoReviewStatus)window.pdPhotoReviewStatus(label,side);
 label.append(input);return label;
}
function editPilotProfile(side){
 const user=window.pdOnboardingUser;if(!user?.driver_application)return;
 pdApplyRoleAccess(user,'driver');document.getElementById('pdPilotWork').classList.add('hidden');document.body.classList.remove('pd-pilot-cabinet','admin-home');
 pdShowOnboarding('driver');
 if(side){const input=document.getElementById('pdPhoto_'+side);if(input&&!input.disabled){input.closest('.pd-document-card')?.scrollIntoView({block:'center'});input.focus()}}
}
function buttons(){
 let nav=document.getElementById('pdPilotNavV4');if(nav)return nav;
 nav=document.createElement('nav');nav.id='pdPilotNavV4';nav.className='actions';nav.setAttribute('aria-label',tr('Разделы кабинета пилота','Pilot cabinet sections','Piloto paskyros skyriai'));
 for(const [key,text]of [['active',tr('Активные заказы','Active orders','Aktyvūs užsakymai')],['history',tr('История поездок','Trip history','Kelionių istorija')],['vehicle',tr('Мой автомобиль','My vehicle','Mano automobilis')],['documents',tr('Документы и фото','Documents and photos','Dokumentai ir nuotraukos')]])nav.append(b(text,()=>{tab=key;pdPilotWork()}));
 const section=document.getElementById('pdPilotWork');section.insertBefore(nav,document.getElementById('pdPilotWorkList'));return nav;
}
pdEnterPilot=function(){
 const user=window.pdOnboardingUser;if(user?.admin===true){pdSetRole('admin');return}if(!user||(!pdPilotEnabled&&!user.driver_application))return;
 pdApplyRoleAccess(user,'driver');pdHideOnboarding();document.body.classList.add('admin-home','pd-pilot-cabinet');
 document.querySelectorAll('section[id^="step"]').forEach(x=>x.classList.add('hidden'));
 document.getElementById('pdPilotWork').classList.remove('hidden');document.getElementById('mainNav').classList.add('hidden');document.getElementById('pdPilotBack').classList.add('hidden');
 document.getElementById('pdPilotWorkTitle').textContent=tr('Кабинет пилота','Pilot cabinet','Piloto paskyra');
 document.getElementById('pdPilotWorkRefresh').textContent=tr('Обновить','Refresh','Atnaujinti');
 const passenger=document.getElementById('pdPilotPassenger');passenger.textContent=tr('Перейти в пассажирский кабинет','Open passenger cabinet','Atidaryti keleivio paskyrą');passenger.classList.add('hidden');
 buttons();pdPilotWork();window.scrollTo(0,0);
};
const oldPassenger=pdPilotPassenger;pdPilotPassenger=function(){document.body.classList.remove('pd-pilot-cabinet');oldPassenger()};
pdPilotWork=async function(){
 if(admin){pdSetRole('admin');return}if(busy)return;busy=true;pilotCardVersion++;if(pilotCardPhotoURL){URL.revokeObjectURL(pilotCardPhotoURL);pilotCardPhotoURL=null}const box=document.getElementById('pdPilotWorkList');box.replaceChildren();buttons();
 try{
  const fresh=await api('/api/me');window.pdOnboardingUser=fresh;pdPilotEnabled=Boolean(fresh.pilot_access);const application=fresh.driver_application;
  if(application?.status==='stage2'){
   line(box,tr('Регистрация','Registration','Registracija'),tr('Первый этап подтверждён. Заполните второй этап: данные авто и документы.','Step one approved. Complete step two: vehicle details and documents.','Pirmas etapas patvirtintas. Užpildykite automobilio duomenis ir dokumentus.'));
   box.append(b(tr('Заполнить второй этап','Complete step two','Užpildyti antrą etapą'),()=>pdShowOnboarding('driver')));
   if(tab==='active'||tab==='history')return;
  }
  if(!pdPilotEnabled){
   const states={pending:tr('Заявка на проверке. Рабочие заказы будут доступны после одобрения.','Application under review. Work orders unlock after approval.','Paraiška tikrinama. Darbo užsakymai bus prieinami patvirtinus.'),rejected:tr('Заявка отклонена. Можно исправить данные и отправить повторно.','Application rejected. Correct your details and submit again.','Paraiška atmesta. Pataisykite duomenis ir pateikite iš naujo.')};
   line(box,tr('Статус заявки','Application status','Paraiškos būsena'),states[application?.status]||tr('Нет допуска к заказам','Work access not granted','Prieiga prie užsakymų nesuteikta'));
   if(tab==='active'||tab==='history')return;
  }
  if(tab==='vehicle'||tab==='documents'){
   if(!application){line(box,tr('Профиль','Profile','Profilis'),tr('Данные заявки отсутствуют','No application data','Paraiškos duomenų nėra'));return}
   if(tab==='vehicle'){
    box.append(pilotCard(application,window.pdOnboardingUser.id));
   }
   for(const [key,title]of Object.entries(photoLabels)){
    if(application.stage!==2&&!pdActiveDocumentSides.includes(key))continue;
    if(tab==='vehicle'&&!key.startsWith('car_'))continue;
    if((application.document_sides||[]).includes(key))box.append(b(title,()=>pdPreviewDocument(key,window.pdOnboardingUser.id)));
    else line(box,title,tr('Не загружено','Not uploaded','Neįkelta'));
    const loaded=(application.document_sides||[]).includes(key);box.append(photoPicker(key,title,loaded));
   }
   line(box,tr('Изменение данных','Update details','Duomenų keitimas'),tr('Повторная отправка заявки возвращает её на проверку диспетчера.','Resubmitting returns the application to admin review.','Pakartotinai pateikta paraiška vėl tikrinama dispatcheriaus.'));
   box.append(b(tr('Обновить данные и фотографии','Update details and photos','Atnaujinti duomenis ir nuotraukas'),()=>editPilotProfile()));return;
  }
  const result=await api('/api/driver/work');const rows=result.orders.filter(o=>tab==='history'?['Выполнена','Отменена'].includes(o.status):!['Выполнена','Отменена'].includes(o.status));
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
   if(order.status==='Подтверждена'&&!order.departed_at&&!order.arrived_at)article.append(b(tr('В пути к пассажиру','On my way to pickup','Vykstu pas keleivį'),async function(){this.disabled=true;try{await window.pdBeginPickupV4(Number(order.id));await pdPilotWork();await window.pdOpenLiveTripV4(Number(order.id))}catch(e){message(pdL(e.message),true)}finally{this.disabled=false}}));
   article.append(b(tr('Открыть рабочую поездку','Open work trip','Atidaryti darbo kelionę'),()=>pdOpenLiveTripV4(order.id)));box.append(article);
  }
 }catch(e){line(box,tr('Ошибка','Error','Klaida'),e.message)}finally{busy=false}
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
