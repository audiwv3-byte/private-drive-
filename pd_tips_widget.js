(()=>{
const lang=window.PD_LANG||document.documentElement.lang||'ru';
const t=(ru,en,lt)=>lang==='en'?en:lang==='lt'?lt:ru;
const style=document.createElement('style');style.textContent=`
#pdTipsLocation{position:static!important;display:flex;justify-content:center;clear:both;margin:24px auto 0;padding:12px;width:100%;max-width:560px;box-sizing:border-box}
#pdTipsAlways{position:static!important;inset:auto!important;transform:none!important;z-index:auto!important;display:inline-flex!important;align-items:center;justify-content:center;visibility:visible!important;width:auto!important;min-height:44px;margin:0!important;padding:11px 20px!important;border:1px solid #d6b467!important;border-radius:12px!important;background:#171512!important;color:#f4d38d!important;font:600 14px system-ui!important;box-shadow:none!important;cursor:pointer}
.pd-global-tip-dialog{box-sizing:border-box;width:min(460px,calc(100% - 24px));max-height:85vh;overflow:auto;padding:22px;background:#151515;color:#f5eee0;border:1px solid #c5a25e;border-radius:18px;font:15px/1.5 system-ui}
.pd-global-tip-dialog::backdrop{background:#000a}.pd-global-tip-dialog button{margin:6px 8px 6px 0;padding:11px 14px;border-radius:10px;border:1px solid #b79a60;background:#211c13;color:#f4d38d;cursor:pointer;font:inherit}.pd-global-tip-dialog select{width:100%;padding:12px;margin:10px 0;border:1px solid #b79a60;border-radius:10px;background:#222;color:#f5eee0;font:inherit}.pd-global-tip-dialog p{overflow-wrap:anywhere}.pd-global-tip-dialog h2{margin-top:0;color:#f4d38d}.pd-tip-methods{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:14px 0}.pd-global-tip-dialog .pd-tip-method{width:100%;min-height:48px;margin:0;text-align:left}.pd-global-tip-dialog .pd-tip-method[aria-pressed=true]{background:#45371f;border-color:#f4d38d;outline:1px solid #f4d38d}`;document.head.append(style);
let button=document.getElementById('pdTipsAlways');if(!button){button=document.createElement('button');button.id='pdTipsAlways'}
button.type='button';button.textContent=t('💛 Чаевые','💛 Tips','💛 Arbatpinigiai');button.title=t('Оставить чаевые в любое время','Leave a tip at any time','Palikite arbatpinigių bet kada');button.removeAttribute('onclick');let location=document.getElementById('pdTipsLocation');if(!location){location=document.createElement('div');location.id='pdTipsLocation';(document.querySelector('main')||document.body).append(location)}location.append(button);
function placeTipsAboveContacts(){
 const onboard=document.body.classList.contains('pd-onboarding-active');
 const anchor=onboard?document.querySelector('#pdOnboarding a[href^="mailto:"]')?.closest('p'):document.querySelector('footer.pd-contact-footer');
 if(anchor&&anchor.parentElement&&(location.parentElement!==anchor.parentElement||location.nextElementSibling!==anchor))anchor.before(location);
}
placeTipsAboveContacts();
new MutationObserver(placeTipsAboveContacts).observe(document.body,{attributes:true,subtree:true,attributeFilter:['class']});

function paragraph(parent,text){const p=document.createElement('p');p.textContent=text;parent.append(p);return p}

button.onclick=async()=>{
 if(document.getElementById('pdGlobalTipDialog'))return;
 const d=document.createElement('dialog');d.id='pdGlobalTipDialog';d.className='pd-global-tip-dialog';
 const h=document.createElement('h2');h.textContent=t('Оставить чаевые','Leave a tip','Palikti arbatpinigių');
 const close=document.createElement('button');close.type='button';close.textContent=t('Закрыть','Close','Uždaryti');
 close.onclick=()=>d.close();d.append(h,close);
 paragraph(d,t('Чаевые добровольные. Выберите удобный способ. Перевод выполняется в банке или кошельке, без автоматического списания.',
  'Tips are optional. Choose a method; transfers happen in your bank or wallet without automatic debits.',
  'Arbatpinigiai savanoriški. Pasirinkite būdą; pervedimai atliekami banke arba piniginėje be automatinio nuskaitymo.'));
 const choices=document.createElement('div');choices.className='pd-tip-methods';choices.setAttribute('role','group');
 choices.setAttribute('aria-label',t('Способ чаевых','Tip method','Arbatpinigių būdas'));
 const info=document.createElement('div');const status=document.createElement('p');status.setAttribute('role','status');
 d.append(choices,info,status);d.addEventListener('close',()=>d.remove(),{once:true});document.body.append(d);d.showModal();
 const menu=[
  {id:'paysera',label:'Paysera'},
  {id:'swedbank',label:'Swedbank'},
  {id:'crypto',label:t('Криптовалюта','Cryptocurrency','Kriptovaliuta')}
 ];
 let response=null,pending=null,selected=null;
 const tops=new Map();
 const line=(parent,value)=>paragraph(parent,value);
 function buttonInto(parent,value,fn){
  const el=document.createElement('button');el.type='button';el.textContent=value;el.onclick=fn;parent.append(el);return el;
 }
 async function copy(value){
  try{await navigator.clipboard.writeText(value);status.textContent=t('Скопировано','Copied','Nukopijuota')}
  catch(_){status.textContent=t('Скопируйте вручную','Copy manually','Nukopijuokite rankiniu būdu')}
 }
 async function fetchOptions(){
  if(response)return response;
  if(pending)return pending;
  pending=(async()=>{
   const initData=window.Telegram?.WebApp?.initData||'';
   if(!initData)throw Error('TELEGRAM_REQUIRED');
   const res=await fetch('/api/tips/options',{headers:{'X-Telegram-Init-Data':initData},cache:'no-store'});
   if(res.status===401||res.status===403)throw Error('TELEGRAM_REQUIRED');
   if(!res.ok)throw Error('LOAD_FAILED');
   return await res.json();
  })();
  try{response=await pending;return response}finally{pending=null}
 }
 function openTelegram(){
  const a=document.createElement('a');a.href='https://t.me/EuroBalticTransferBot?start=tips';
  a.className='pd-tip-open-telegram';
  a.style.cssText='display:block;padding:12px 16px;margin:12px 0;border:1px solid #d6b467;border-radius:10px;color:#f4d38d;text-align:center;text-decoration:none';
  a.textContent=t('Открыть в Telegram','Open in Telegram','Atidaryti Telegram');
  a.onclick=e=>{const tg=window.Telegram?.WebApp;if(tg?.openTelegramLink){e.preventDefault();tg.openTelegramLink(a.href)}};
  info.append(a);
 }
 async function select(id){
  selected=id;for(const [k,btn] of tops)btn.setAttribute('aria-pressed',String(k===id));
  info.replaceChildren();status.textContent=t('Загружаем реквизиты…','Loading details…','Įkeliami duomenys…');
  let opts;
  try{opts=await fetchOptions()}catch(e){
   if(id!==selected)return;
   if(e.message==='TELEGRAM_REQUIRED'){
    status.textContent=t('Откройте Mini App через Telegram, чтобы увидеть реквизиты. Регистрация не нужна.',
      'Open the Mini App through Telegram to view the details. No registration needed.',
      'Atidarykite mini programėlę per Telegram, kad matytumėte duomenis. Registracija nebūtina.');
    openTelegram();
   }else status.textContent=t('Не удалось загрузить реквизиты. Попробуйте ещё раз.',
     'Could not load payment details. Please retry.',
     'Nepavyko įkelti mokėjimo duomenų. Bandykite dar kartą.');
   return;
  }
  if(id!==selected)return;status.textContent='';
  if(id==='crypto'){
   line(info,t('Выберите криптовалюту','Choose cryptocurrency','Pasirinkite kriptovaliutą'));
   const coins=document.createElement('div');coins.className='pd-tip-methods';coins.setAttribute('role','group');
   coins.setAttribute('aria-label',t('Валюта','Currency','Valiuta'));
   info.append(coins);const details=document.createElement('div');info.append(details);
   for(const ticker of ['USDC','BTC','ETH']){
    const coin=buttonInto(coins,ticker,()=>{
     for(const other of coins.children)other.setAttribute('aria-pressed',String(other===coin));
     details.replaceChildren();
     const x=(opts.crypto||[]).find(v=>v.currency===ticker&&v.address);
     if(!x){line(details,t('Кошелёк для этой валюты пока не настроен. Не отправляйте перевод.',
       'Wallet unavailable for this currency. Do not send funds.',
       'Šios valiutos piniginė nenustatyta. Nesiųskite lėšų.'));return}
     line(details,x.currency+' · '+x.network);line(details,x.address);
     buttonInto(details,t('Копировать адрес','Copy address','Kopijuoti adresą'),()=>copy(x.address));
     line(details,t('Переводите только в указанной сети. Комиссия сети оплачивается отдельно.',
       'Use only the displayed network. Network fees are separate.',
       'Naudokite tik nurodytą tinklą. Tinklo mokesčiai mokami atskirai.'));
    });coin.className='pd-tip-method';coin.setAttribute('aria-pressed','false');
   }
   return;
  }
  const bank=(opts.banks||[]).find(v=>v.id===id);
  if(!bank?.iban||!bank?.recipient){
   line(info,t('Реквизиты банка пока не подключены. Не выполняйте перевод.',
     'Bank details are not configured yet. Do not transfer.',
     'Banko duomenys dar nenustatyti. Nesiųskite pervedimo.'));return
  }
  line(info,bank.bank+' · '+bank.recipient);
  line(info,'IBAN: '+bank.iban+(bank.bic?' · BIC: '+bank.bic:''));
  buttonInto(info,t('Копировать IBAN','Copy IBAN','Kopijuoti IBAN'),()=>copy(bank.iban));
  if(opts.reference){
   line(info,t('Назначение: ','Reference: ','Paskirtis: ')+opts.reference);
   buttonInto(info,t('Копировать назначение','Copy reference','Kopijuoti paskirtį'),()=>copy(opts.reference));
  }
  line(info,t('Сумма чаевых — на ваше усмотрение, в EUR.',
    'Tip any amount in EUR.','Pasirinkite norimą arbatpinigių sumą eurais.'));
 }
 for(const item of menu){
  const option=document.createElement('button');option.type='button';option.className='pd-tip-method';
  option.textContent=(item.id==='crypto'?'◇ ':'🏦 ')+item.label;
  option.setAttribute('aria-pressed','false');option.onclick=()=>select(item.id);
  choices.append(option);tops.set(item.id,option);
 }
};
window.pdOpenTipInfo=()=>button.click();
const tipStart=new URLSearchParams(window.location.search).get('start')||window.Telegram?.WebApp?.initDataUnsafe?.start_param;if(tipStart==='tips')requestAnimationFrame(()=>button.click());
})();
