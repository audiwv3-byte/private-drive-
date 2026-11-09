/* Visible in-app passenger notifications; no payment is initiated automatically. */
(()=>{
'use strict';
const t=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
let busy=false,deepHandled=false;const memorySeen=new Set();
const storageKey=e=>'pdPassengerNoticeV5:'+window.pdOnboardingUser.id+':'+e.key;
const seen=e=>{try{return memorySeen.has(e.key)||localStorage.getItem(storageKey(e))==='yes'}catch(_){return memorySeen.has(e.key)}};
const mark=e=>{memorySeen.add(e.key);try{localStorage.setItem(storageKey(e),'yes')}catch(_){}};
function addButton(parent,label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await fn()}catch(e){const p=document.createElement('p');p.setAttribute('role','alert');p.textContent=e.message;parent.append(p)}finally{b.disabled=false}};parent.append(b)}
async function pay(id){if(admin)pdSetRole('client');else if(document.body.classList.contains('pd-pilot-cabinet'))pdPilotPassenger();go(8);await openPay(Number(id))}
async function poll(){
 if(busy||document.hidden||!initData||!window.pdOnboardingUser?.registered)return;
 const start=new URLSearchParams(location.search).get('start')||window.Telegram?.WebApp?.initDataUnsafe?.start_param||'';
 if(!deepHandled&&/^pay_[1-9][0-9]*$/.test(start)){deepHandled=true;await pay(Number(start.slice(4)));return}
 if(document.body.classList.contains('pd-pilot-cabinet')||(admin&&pdAdminView!=='client')||document.querySelector('dialog[open],.pd-client-dialog'))return;
 busy=true;
 try{const data=await api('/api/passenger/notices');const e=(data.events||[]).find(x=>!seen(x));if(!e)return;
 // A notice may have been queued before payment was confirmed or claimed.
 // Check the current ledger before showing any request to pay again.
 if(e.kind==='payment'){
  const payment=await api('/api/payment/'+Number(e.order_id));
  if(payment.status!=='Подтверждена'||['Оплачено','Перевод на проверке','Криптоперевод на проверке'].includes(payment.payment_status))return;
  e.amount=payment.price;
  if(!e.amount)return;
 }
 if(document.hidden||document.querySelector('dialog[open],.pd-client-dialog')||document.body.classList.contains('pd-pilot-cabinet')||(admin&&pdAdminView!=='client'))return;
 const headings={payment:t('Заказ принят — оплатите поездку','Booking accepted — pay for your trip','Užsakymas patvirtintas — apmokėkite kelionę'),assigned:t('Пилот назначен','Pilot assigned','Pilotas priskirtas'),pickup:t('Пилот в пути к вам','Pilot is on the way','Pilotas vyksta pas jus'),arrived:t('Машина прибыла','Your car has arrived','Automobilis atvyko')};
 const d=pdSimpleDialog(headings[e.kind]||headings.assigned);d.id='pdPassengerNoticeV5';
 const order=document.createElement('h3');order.textContent=t('Заказ №','Order #','Užsakymas Nr. ')+e.order_id;d.append(order);
 for(const value of [e.pilot,[e.vehicle,e.plate].filter(Boolean).join(' · ')]){const p=document.createElement('p');p.textContent=value||'';d.append(p)}
 const p=document.createElement('p');p.style.fontSize='18px';
 if(e.kind==='payment'){p.textContent=t('Заказ подтверждён диспетчером, пилот назначен. К оплате: ','Dispatcher accepted your booking and assigned a pilot. Amount due: ','Dispatcherius patvirtino užsakymą ir priskyrė pilotą. Mokėti: ')+e.amount+' €';d.append(p);addButton(d,t('💳 Оплатить поездку','💳 Pay for trip','💳 Apmokėti kelionę'),async()=>{d.close();await pay(e.order_id)})}
 else if(e.kind==='assigned'){p.textContent=t('Пилот назначен. Ожидайте подтверждения заказа диспетчером.','Pilot assigned. Await dispatcher confirmation.','Pilotas priskirtas. Laukite dispatcheriaus patvirtinimo.');d.append(p)}
 else {p.textContent=e.kind==='arrived'?t('Первые 5 минут ожидания бесплатны. Подробности — в заказе.','The first 5 waiting minutes are free. See your order for details.','Pirmosios 5 laukimo minutės nemokamos. Išsamiau — užsakyme.'):t('Следите за автомобилем на карте в приложении.','Follow your car on the in-app map.','Stebėkite automobilį programėlės žemėlapyje.');d.append(p);addButton(d,t('📍 Показать машину на карте','📍 Show car on map','📍 Rodyti automobilį žemėlapyje'),async()=>{d.close();await pdOpenLiveTripV4(e.order_id)})}
 if(typeof pdOpenOrderPilot==='function')addButton(d,t('Карточка пилота','Pilot card','Piloto kortelė'),()=>{d.close();pdOpenOrderPilot(e.order_id)});
 d.addEventListener('close',()=>mark(e),{once:true});
 }catch(_){/* Retry on next poll without claiming a delivered event. */}finally{busy=false}
}
setInterval(poll,8000);setTimeout(poll,1800);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
})();


