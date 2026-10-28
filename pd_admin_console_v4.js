/* Unified admin console. No financial operation runs merely by opening a card. */
(()=>{
'use strict';
const text=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const $id=id=>document.getElementById(id);
const euros=c=>(Number(c||0)/100).toFixed(2)+' €';
const clock=s=>s===null||s===undefined?'—':Math.floor(s/3600)+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
const when=t=>t?new Date(t*1000).toLocaleString(window.PD_LANG||'ru',{timeZone:'Europe/Vilnius'}):'—';
let root=null,list=null,panel=null,filter='all',query='',day='',cursor=null,selected=null,record=null,currentTab='overview',dirty=false,busy=false,lastLoaded=0,searchTimer=null;
const statusNames={all:text('Все','All','Visi'),unpaid:text('Не оплачены','Unpaid','Neapmokėti'),unassigned:text('Без пилота','Unassigned','Nepriskirti'),waiting:text('Ожидание','Waiting','Laukimas')};
const titles={overview:text('Обзор','Overview','Apžvalga'),route:text('Маршрут','Route','Maršrutas'),time:text('Время','Timing','Laikas'),pilot:text('Пилот','Pilot','Pilotas'),money:text('Оплата','Payment','Mokėjimas'),history:text('История','History','Istorija')};
function el(tag,content,className){const n=document.createElement(tag);if(content!==undefined)n.textContent=content;if(className)n.className=className;return n}
function btn(label,fn,primary=false){const b=el('button',label,primary?'pda-primary':'secondary');b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn()}catch(e){message(e.message,true)}finally{b.disabled=false}};return b}
function field(parent,label,value){const box=el('div',undefined,'pda-field');box.append(el('span',label),el('strong',value===null||value===undefined||value===''?'—':String(value)));parent.append(box)}
function section(parent,label){const h=el('h3',label);parent.append(h)}
function contact(parent,label,value,href){if(!value)return;const row=el('p');row.append(el('span',label+': '));const a=el('a',value);a.href=href;row.append(a);parent.append(row)}
function internalFinance(){showLegacy();$id('pdTabFinance')?.click()}
function showLegacy(){if(root)root.hidden=true;$id('step10')?.classList.remove('pda-console-active');$id('pdAdminConsoleReturnV4')?.removeAttribute('hidden')}
async function renderList(append=false){
 if(busy||!root||root.hidden)return;busy=true;
 try{
  const params=new URLSearchParams({q:query,status:filter,limit:'25'});if(day)params.set('date',day);if(append&&cursor)params.set('before',cursor);
  const d=await api('/api/admin/console/orders?'+params);cursor=d.next_before;
  if(!append)list.replaceChildren();
  for(const o of d.orders){
   const b=btn('',()=>openOrder(o.id));b.className='pda-order'+(selected===Number(o.id)?' selected':'');b.dataset.orderId=o.id;
   const head=el('div',undefined,'pda-order-head');head.append(el('strong','№'+o.id),el('span',pdL(o.status),'pill'));b.append(head);
   b.append(el('p',o.origin+' → '+o.destination),el('small',o.trip_date+' · '+o.trip_time));
   b.append(el('p',o.customer_name||text('Клиент','Customer','Klientas'),'pda-muted'));
   b.append(el('small',(o.pilot_name||text('Пилот не назначен','Pilot not assigned','Pilotas nepriskirtas'))+(o.plate?' · '+o.plate:'')));
   const cost=o.final_cents!==null?euros(o.final_cents):(o.price?o.price+' €':text('Нужен пересчёт','Repricing needed','Reikia perskaičiuoti'));
   b.append(el('div',cost+' · '+pdL(o.payment_status),'pda-order-total'));
   if(o.started_at)b.append(el('small',text('Движение: ','Driving: ','Važiavimas: ')+clock(o.drive_seconds)));
   if(o.arrived_at&&!o.started_at)b.append(el('small',text('Пилот прибыл · идёт ожидание','Pilot arrived · waiting','Pilotas atvyko · laukiama')));
   list.append(b);
  }
  if(!list.children.length)list.append(el('p',text('Заказов по фильтру нет','No matching orders','Užsakymų pagal filtrą nėra')));
  $id('pdAdminMoreV4').hidden=!cursor;
  $id('pdAdminStatsV4').replaceChildren();
  const stats=[['Новая',text('Новые','New','Nauji')],['Подтверждена',text('Подтверждены','Confirmed','Patvirtinti')],['В пути',text('В пути','Driving','Kelyje')],['unpaid',text('Не оплачены','Unpaid','Neapmokėti')]];
  for(const[key,label]of stats){const b=btn('',()=>{filter=key;$id('pdAdminStatusV4').value=key;return renderList()});b.className='pda-stat';b.append(el('strong',String(key==='unpaid'?d.unpaid:d.counts[key]||0)),el('span',label));$id('pdAdminStatsV4').append(b)}
  lastLoaded=Date.now();$id('pdAdminUpdatedV4').textContent=text('Обновлено: ','Updated: ','Atnaujinta: ')+new Date(lastLoaded).toLocaleTimeString();
 }finally{busy=false}
}
function formField(form,label,key,value,type='text'){
 const wrap=el('label',label),input=type==='textarea'?el('textarea'):el('input');input.name=key;input.value=value??'';
 if(type!=='textarea')input.type=type;if(key==='passengers'){input.min='1';input.max='8'}if(key==='details')input.maxLength=2000;
 input.oninput=()=>{dirty=true};wrap.append(input);form.append(wrap);return input;
}
async function saveChanges(changes,reason){
 await api('/api/admin/console/orders/'+selected,{revision:record.revision,reason,changes});dirty=false;await openOrder(selected);await renderList();message(text('Изменения сохранены в журнале','Changes saved to audit history','Pakeitimai išsaugoti žurnale'));
}
function actionDialog(action,label){
 const d=pdSimpleDialog(label);d.append(el('p',text('Укажите причину. Действие и администратор будут записаны в историю заказа.','Give a reason. The action and administrator are recorded in the order history.','Nurodykite priežastį. Veiksmas ir administratorius bus įrašyti užsakymo istorijoje.')));
 const reason=el('textarea');reason.placeholder=text('Причина действия','Reason for action','Veiksmo priežastis');reason.maxLength=500;d.append(reason);
 d.append(btn(text('Подтвердить действие','Confirm action','Patvirtinti veiksmą'),async()=>{if(reason.value.trim().length<3)throw Error(text('Укажите причину','Give a reason','Nurodykite priežastį'));await api('/api/admin/console/orders/'+selected+'/action',{action,reason:reason.value.trim()});d.close();await openOrder(selected);await renderList()},true));
}
function renderDetail(){
 if(!record)return;panel.replaceChildren();const o=record.order;
 const header=el('div',undefined,'pda-detail-head');header.append(el('h2',text('Заказ №','Order #','Užsakymas Nr. ')+selected),el('span',pdL(o.status),'pill'));panel.append(header);
 const links=el('div',undefined,'pda-actions');links.append(btn(text('Карточка клиента','Customer card','Kliento kortelė'),()=>pdOpenCustomer(o.telegram_id)),btn(text('Обновить заказ','Refresh order','Atnaujinti užsakymą'),async()=>{if(dirty&&!confirm(text('Несохранённые изменения будут потеряны. Обновить?','Unsaved changes will be lost. Refresh?','Neišsaugoti pakeitimai bus prarasti. Atnaujinti?')))return;dirty=false;await openOrder(selected)}));panel.append(links);
 const tabs=el('nav',undefined,'pda-tabs');tabs.setAttribute('aria-label',text('Разделы заказа','Order sections','Užsakymo skyriai'));
 for(const[key,title]of Object.entries(titles)){const b=btn(title,()=>{if(dirty&&!confirm(text('Перейти без сохранения изменений?','Leave without saving?','Išeiti neišsaugojus?')))return;dirty=false;currentTab=key;renderDetail()});b.setAttribute('aria-pressed',String(currentTab===key));tabs.append(b)}panel.append(tabs);
 const content=el('div',undefined,'pda-content');panel.append(content);
 if(currentTab==='overview'){
  const grid=el('div',undefined,'pda-grid');field(grid,text('Маршрут','Route','Maršrutas'),[o.origin,o.stop_address,o.destination].filter(Boolean).join(' → '));field(grid,text('Подача','Pickup','Paėmimas'),o.trip_date+' '+o.trip_time);field(grid,text('Пассажир','Passenger','Keleivis'),record.customer?.name);field(grid,text('Пилот','Pilot','Pilotas'),record.pilot?.name);field(grid,text('Автомобиль','Vehicle','Automobilis'),record.pilot?[record.pilot.vehicle,record.pilot.plate].join(' · '):'—');field(grid,text('Время движения','Driving time','Važiavimo laikas'),clock(record.drive_seconds));field(grid,text('Ожидание','Waiting','Laukimas'),clock(record.waiting_seconds));field(grid,text('Сумма','Fare','Kaina'),record.final_cents===null||record.final_cents===undefined?o.price+' €':euros(record.final_cents));field(grid,text('Оплата','Payment','Mokėjimas'),pdL(o.payment_status));content.append(grid);
  section(content,text('Действия с поездкой','Trip actions','Kelionės veiksmai'));const actions=el('div',undefined,'pda-actions');
  if(o.status==='Новая')actions.append(btn(text('Подтвердить заказ','Confirm booking','Patvirtinti užsakymą'),async()=>{await setStatus(selected,'Подтверждена');await openOrder(selected);await renderList()}));
  if(o.status==='Подтверждена')actions.append(btn(record.arrived_at?text('Начать поездку','Start trip','Pradėti kelionę'):text('Отметить прибытие','Mark arrival','Pažymėti atvykimą'),()=>actionDialog(record.arrived_at?'start':'arrive',text('Изменение этапа поездки','Change trip stage','Keisti kelionės etapą'))));
  if(o.status==='В пути')actions.append(btn(text('Завершить поездку','Complete trip','Baigti kelionę'),()=>actionDialog('finish',text('Завершение поездки','Trip completion','Kelionės užbaigimas'))));
  if(['Новая','Подтверждена'].includes(o.status))actions.append(btn(text('Отмена и возврат','Cancellation and refund','Atšaukimas ir grąžinimas'),internalFinance));
  actions.append(btn(text('Карта и текущая поездка','Map and live trip','Žemėlapis ir dabartinė kelionė'),()=>pdOpenLiveTripV4(selected)));content.append(actions);
  section(content,text('Внутренняя заметка','Internal note','Vidinė pastaba'));content.append(el('p',text('Видна только администраторам. Не меняет пожелания пассажира.','Visible to administrators only. Does not change passenger requests.','Matoma tik administratoriams. Nekeičia keleivio pageidavimų.'),'pda-muted'));
  const note=el('textarea');note.value=record.admin_note||'';note.maxLength=2000;note.oninput=()=>{dirty=true};content.append(note);
  content.append(btn(text('Сохранить заметку','Save note','Išsaugoti pastabą'),()=>saveChanges({admin_note:note.value},text('Обновление внутренней заметки','Internal note updated','Vidinės pastabos atnaujinimas'))));
 }else if(currentTab==='route'){
  if(record.edit_locks.length){content.append(el('p',text('Изменение параметров заблокировано: ','Trip edits are locked: ','Kelionės keitimas užrakintas: ')+record.edit_locks.join(' · '),'pda-warning'));content.append(el('p',text('Для оплаченной поездки используйте согласованные доплаты или возврат. Исходные параметры и платёж не перезаписываются.','For paid trips use consented extras or a refund. Original details and payments are not overwritten.','Apmokėtai kelionei naudokite suderintas priemokas arba grąžinimą. Pradiniai duomenys ir mokėjimas neperrašomi.')));return}
  content.append(el('p',text('После изменения параметров прежняя цена сбросится. Заказ потребуется пересчитать и подтвердить заново.','Changing trip details clears the old quote. Reprice and reconfirm the booking.','Pakeitus kelionės duomenis ankstesnė kaina panaikinama. Reikia perskaičiuoti ir patvirtinti iš naujo.'),'pda-warning'));
  const form=el('form',undefined,'pda-form');form.onsubmit=e=>e.preventDefault();
  formField(form,text('Адрес подачи','Pickup address','Paėmimo adresas'),'origin',o.origin);formField(form,text('Адрес назначения','Destination','Kelionės tikslas'),'destination',o.destination);formField(form,text('Дополнительная остановка','Extra stop','Papildomas sustojimas'),'stop_address',o.stop_address||'');
  const date=o.trip_date?.split('.').reverse().join('-');formField(form,text('Дата','Date','Data'),'trip_date',date,'date');formField(form,text('Время','Time','Laikas'),'trip_time',o.trip_time,'time');formField(form,text('Пассажиров','Passengers','Keleivių'),'passengers',o.passengers,'number');formField(form,text('Багаж','Luggage','Bagažas'),'luggage',o.luggage);formField(form,text('Пожелания к поездке','Trip requests','Kelionės pageidavimai'),'details',o.details,'textarea');const reason=formField(form,text('Причина изменения','Reason for change','Pakeitimo priežastis'),'reason','','textarea');content.append(form);
  content.append(btn(text('Сохранить изменения заказа','Save order changes','Išsaugoti užsakymo pakeitimus'),async()=>{const changes={};for(const input of form.elements){if(!input.name||input.name==='reason')continue;let value=input.name==='passengers'?Number(input.value):input.name==='trip_date'?input.value.split('-').reverse().join('.'):input.value;if(String(value)!==String(o[input.name]??''))changes[input.name]=value}if(!Object.keys(changes).length)return;await saveChanges(changes,reason.value)},true));
 }else if(currentTab==='time'){
  for(const[label,value]of [[text('Время подачи по заказу','Scheduled pickup','Numatytas paėmimas'),o.trip_date+' '+o.trip_time],[text('Прибытие пилота','Pilot arrival','Piloto atvykimas'),when(record.arrived_at)],[text('Начало движения','Driving started','Važiavimo pradžia'),when(record.started_at)],[text('Завершение','Completed','Pabaiga'),when(record.ended_at)],[text('Фактическое движение','Actual driving','Faktinis važiavimas'),clock(record.drive_seconds)],[text('Ожидание','Waiting','Laukimas'),clock(record.waiting_seconds)],[text('Всего с прибытия','Total since arrival','Iš viso nuo atvykimo'),clock(record.total_service_seconds)],[text('Прогноз маршрута, мин','Route estimate, min','Maršruto prognozė, min'),o.duration_min]])field(content,label,value);
  content.append(el('p',text('Неизвестное фактическое время обозначено «—». Прогноз маршрута не считается временем выполненной поездки.','Unknown actual time is shown as “—”. Route estimates are separate from actual trip duration.','Nežinomas faktinis laikas žymimas „—“. Maršruto prognozė atskirta nuo faktinės trukmės.'),'pda-muted'));
 }else if(currentTab==='pilot'){
  const p=record.pilot;if(p){field(content,text('Имя','Name','Vardas'),p.name);contact(content,text('Телефон','Phone','Telefonas'),p.phone,'tel:'+String(p.phone||'').replace(/[^+0-9]/g,''));field(content,text('Автомобиль','Vehicle','Automobilis'),[p.vehicle,p.vehicle_year,p.plate].join(' · '));field(content,text('Мест','Seats','Vietų'),p.seats);for(const side of p.document_sides||[])content.append(btn(pdL(pdDocumentLabels[side]||side),()=>pdPreviewDocument(side,p.telegram_id)))}else content.append(el('p',text('Пилот пока не назначен','Pilot is not assigned','Pilotas dar nepriskirtas')));
  if(['Новая','Подтверждена'].includes(o.status)&&!record.arrived_at)content.append(btn(text('Назначить / заменить пилота','Assign / replace pilot','Priskirti / pakeisti pilotą'),async()=>{await pdAssignPilot(selected)}));
 }else if(currentTab==='money'){
  field(content,text('Основная цена','Base fare','Pagrindinė kaina'),euros(record.base_cents));field(content,text('Ожидание','Waiting','Laukimas'),euros(record.wait_cents));field(content,text('Итоговая стоимость','Final fare','Galutinė kaina'),record.final_cents===null||record.final_cents===undefined?'—':euros(record.final_cents));field(content,text('Способ оплаты','Payment method','Mokėjimo būdas'),o.payment_method);field(content,text('Статус оплаты','Payment status','Mokėjimo būsena'),pdL(o.payment_status));field(content,text('Состояние списания','Capture state','Nuskaitymo būsena'),record.capture?.state||'—');
  if(record.cancellation)field(content,text('Возврат','Refund','Grąžinimas'),record.cancellation.state+' · '+euros(record.cancellation.refund_cents));
  section(content,text('Остановки и доплаты','Stops and extras','Sustojimai ir priemokos'));for(const extra of record.extras||[])field(content,extra.reason,euros(extra.amount_cents)+' · '+extra.state);
  const actions=el('div',undefined,'pda-actions');if(!record.edit_locks.length)actions.append(btn(text('Изменить цену','Change price','Keisti kainą'),()=>changePriceV2(selected,String(o.price||''))));actions.append(btn(text('Счета, подтверждения, доплаты и возвраты','Invoices, confirmations, extras and refunds','Sąskaitos, patvirtinimai, priemokos ir grąžinimai'),internalFinance));content.append(actions);
  content.append(el('p',text('Открытие карточки не списывает деньги. Поступление, возврат и доплата — разные операции с собственной проверкой.','Opening an order never charges money. Receipt, refund and extra charge are separate verified operations.','Atidarius užsakymą pinigai nenuskaitomi. Gavimas, grąžinimas ir priemoka yra atskiros tikrinamos operacijos.'),'pda-muted'));
 }else if(currentTab==='history'){
  section(content,text('Изменения администратора','Admin changes','Administratoriaus pakeitimai'));for(const event of record.audit||[]){const card=el('article',undefined,'pda-audit');card.append(el('strong',event.created_at+' · ID '+event.admin_id),el('p',event.reason));for(const key of new Set([...Object.keys(event.before),...Object.keys(event.after)])){if(JSON.stringify(event.before[key])!==JSON.stringify(event.after[key]))field(card,key,String(event.before[key]??'—')+' → '+String(event.after[key]??'—'))}content.append(card)}
  section(content,text('История цены','Price history','Kainos istorija'));for(const ev of record.price_history||[])field(content,ev.created_at||ev.changed_at||'—',String(ev.old_price)+' € → '+String(ev.new_price)+' € · '+String(ev.reason||''));
  section(content,text('Назначения пилота','Pilot assignments','Piloto priskyrimai'));for(const ev of record.pilot_history||[])field(content,ev.changed_at||'—','ID '+String(ev.pilot_id||'—')+' · '+text('Администратор ID ','Administrator ID ','Administratoriaus ID ')+String(ev.admin_id));
  section(content,text('Хронология поездки','Trip timeline','Kelionės chronologija'));for(const ev of record.events||[])field(content,when(ev.created_at),ev.event+' · ID '+ev.actor_id);
 }
}
async function openOrder(id){
 if(dirty&&Number(id)!==selected&&!confirm(text('Перейти без сохранения?','Leave without saving?','Išeiti neišsaugojus?')))return;
 const data=await api('/api/admin/console/orders/'+Number(id));selected=Number(id);record=data;dirty=false;renderDetail();
 list?.querySelectorAll('[data-order-id]').forEach(b=>b.classList.toggle('selected',Number(b.dataset.orderId)===selected));
}
function mount(){
 if(root||!admin||!$id('step10'))return;
 const style=el('style');style.textContent=`.pda-console-active>:not(#pdAdminDashboardV4):not(#pdAdminConsoleReturnV4){display:none!important}#pdAdminDashboardV4{color:#eee7d8}#pdAdminDashboardV4 button{font:inherit;cursor:pointer}.pda-heading,.pda-detail-head,.pda-order-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.pda-heading h1{margin:0;font-size:27px}.pda-actions,.pda-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.pda-actions button,.pda-tabs button{padding:10px 13px;border-radius:10px}.pda-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}.pda-stat{background:#1e1e1d;color:#e8ca88;border:1px solid #4a4334;border-radius:12px;padding:13px;display:grid;gap:3px;text-align:left}.pda-stat strong{font-size:25px}.pda-stat span{font-size:12px;color:#b9b1a1}.pda-filters{display:grid;grid-template-columns:2fr 1fr 1fr;gap:9px;margin:14px 0}.pda-filters input,.pda-filters select,.pda-form input,.pda-form textarea,.pda-content>textarea{box-sizing:border-box;width:100%;background:#121315;border:1px solid #554b38;color:#f5efdf;border-radius:10px;padding:12px}.pda-layout{display:grid;grid-template-columns:minmax(240px,.85fr) minmax(0,1.7fr);gap:18px;align-items:start}.pda-orders{display:grid;gap:10px;max-height:75vh;overflow:auto;padding-right:4px}.pda-order{width:100%;background:#18191a;color:#eee7d8;text-align:left;border:1px solid #494438;border-radius:12px;padding:14px}.pda-order.selected{background:#302a1e;border-color:#e4c27d}.pda-order p{margin:9px 0;line-height:1.4}.pda-order small,.pda-muted{color:#aba394;font-size:12px}.pda-order-total{margin-top:10px;font-size:13px;color:#e8ca88}.pda-panel{border:1px solid #5a4c34;border-radius:14px;padding:20px;background:#151617;min-height:460px;overflow-wrap:anywhere}.pda-detail-head h2{margin:0;font-size:24px}.pda-tabs{border-bottom:1px solid #4b4438;padding-bottom:12px}.pda-tabs button[aria-pressed=true]{background:#e1bf7a;color:#19150d}.pda-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pda-field{display:grid;gap:5px;padding:11px 0;border-bottom:1px solid #302e28}.pda-field span{font-size:12px;color:#b3a994}.pda-field strong{font-size:14px;font-weight:500}.pda-warning{border:1px solid #9a7339;background:#302719;border-radius:10px;padding:12px;color:#efce93}.pda-primary{background:#d9b875;color:#17130b;border:1px solid #edcf92;border-radius:10px;padding:12px 16px}.pda-form{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pda-form label{display:grid;gap:6px;font-size:13px;color:#cbbb9a}.pda-form textarea{min-height:100px}.pda-content>textarea{min-height:90px}.pda-audit{border-left:2px solid #ac8c51;padding:12px;margin:12px 0;background:#1c1c1b}.pda-content h3{color:#e6c98e;margin:20px 0 10px}.pda-status{font-size:12px;color:#aa9f8d}@media(min-width:1000px){body.admin-home main{max-width:1240px!important}}@media(max-width:760px){.pda-layout{grid-template-columns:1fr}.pda-orders{max-height:38vh}.pda-stats{grid-template-columns:repeat(2,1fr)}.pda-filters{grid-template-columns:1fr 1fr}.pda-filters input[type=search]{grid-column:1/-1}.pda-form{grid-template-columns:1fr}.pda-heading{align-items:flex-start;flex-direction:column}.pda-panel{padding:14px}.pda-grid{grid-template-columns:1fr 1fr}.pda-tabs button{padding:9px;font-size:12px}}`;
 document.head.append(style);root=el('div');root.id='pdAdminDashboardV4';
 const heading=el('div',undefined,'pda-heading');heading.append(el('h1',text('Управление заказами','Order management','Užsakymų valdymas')));
 const actions=el('div',undefined,'pda-actions');actions.append(btn(text('Обновить список','Refresh list','Atnaujinti sąrašą'),()=>renderList()),btn(text('Финансы и настройки','Finance and settings','Finansai ir nustatymai'),internalFinance));heading.append(actions);root.append(heading);
 const stats=el('div',undefined,'pda-stats');stats.id='pdAdminStatsV4';root.append(stats);
 const filters=el('div',undefined,'pda-filters');const search=el('input');search.type='search';search.placeholder=text('№ заказа, клиент, телефон, маршрут, пилот…','Order #, customer, phone, route, pilot…','Užsakymo Nr., klientas, telefonas, maršrutas, pilotas…');search.setAttribute('aria-label',search.placeholder);search.oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{query=search.value;cursor=null;renderList()},300)};
 const select=el('select');select.id='pdAdminStatusV4';for(const key of ['all',...Object.keys(statusNames).filter(k=>k!=='all'),'Новая','Подтверждена','В пути','Выполнена','Отменена']){const o=el('option',statusNames[key]||pdL(key));o.value=key;select.append(o)}select.setAttribute('aria-label',text('Фильтр заказов','Order filter','Užsakymų filtras'));select.onchange=()=>{filter=select.value;cursor=null;renderList()};
 const date=el('input');date.type='date';date.setAttribute('aria-label',text('Дата подачи','Pickup date','Paėmimo data'));date.onchange=()=>{day=date.value;cursor=null;renderList()};filters.append(search,select,date);root.append(filters);
 const status=el('p','', 'pda-status');status.id='pdAdminUpdatedV4';root.append(status);
 const layout=el('div',undefined,'pda-layout'),left=el('div');list=el('div',undefined,'pda-orders');left.append(list);const more=btn(text('Ещё заказы','More orders','Daugiau užsakymų'),()=>renderList(true));more.id='pdAdminMoreV4';more.hidden=true;left.append(more);panel=el('section',undefined,'pda-panel');panel.append(el('h2',text('Выберите заказ','Select an order','Pasirinkite užsakymą')),el('p',text('Здесь появятся все параметры, действия и история.','Order details, actions and history appear here.','Čia bus rodomi visi duomenys, veiksmai ir istorija.')));layout.append(left,panel);root.append(layout);
 $id('step10').prepend(root);const back=btn(text('Открыть панель управления заказами','Open order console','Atidaryti užsakymų valdymą'),show);back.id='pdAdminConsoleReturnV4';back.hidden=true;$id('step10').prepend(back);
}
function show(){mount();if(!root)return;root.hidden=false;$id('step10').classList.add('pda-console-active');$id('pdAdminConsoleReturnV4').hidden=true;renderList().catch(e=>message(e.message,true))}
window.pdShowAdminConsoleV4=show;
const oldGo=go;go=function(n){oldGo(n);if(n===10&&admin)show()};
let attempts=0;const starter=setInterval(()=>{if(admin){mount();if(!$id('step10').classList.contains('hidden'))show();clearInterval(starter)}else if(++attempts>60)clearInterval(starter)},500);
setInterval(()=>{if(root&&!root.hidden&&!$id('step10').classList.contains('hidden')&&!document.hidden&&!dirty){renderList().catch(()=>{});if(selected)openOrder(selected).catch(()=>{})}},15000);
})();
