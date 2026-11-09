'use strict';
// No browser is controlled. jsdom evaluates local snapshots with fake API calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM}=require('jsdom');
const root=__dirname,html=fs.readFileSync(path.join(root,'live-index.html'),'utf8');
const before=process.argv.includes('--before');
function source(name,publicName){return fs.readFileSync(path.join(root,before?'public':'release',before?publicName:name),'utf8')}
function setup(signed=false,registered=false,lang='ru'){
 const dom=new JSDOM(html,{url:'https://private-drive.test/?lang='+lang,runScripts:'outside-only'}),w=dom.window,d=w.document;
 const calls={register:0,complete:0,telegram:0,driver:0,api:[]};
 w.PD_LANG=lang;w.initData=signed?'FAKE_LOCAL_ONLY':'';w.pdOnboardingUser={id:101,registered};
 w.pdSwitchLanguage=()=>{};w.pdShowOnboarding=()=>{};
 w.pdCompletePassengerRegistration=async()=>{calls.complete++};
 w.api=async(url,body)=>{calls.api.push({url,body});return {profile:{email:'saved@example.test',home_city:'Vilnius',preferences:'Quiet'}}};
 w.pdRegisterPassenger=async()=>{calls.register++;await w.pdCompletePassengerRegistration()};
 w.pdRegisterPassengerTelegram=async()=>{if(!d.getElementById('pdObPhoneConsent').checked||!w.initData)return;calls.telegram++};
 w.pdRegisterDriver=async()=>{if(d.getElementById('pdObDriver').checkValidity())calls.driver++};
 w.eval(source('pd_registration.js','pd-registration.js'));
 return {dom,w,d,calls,close:()=>w.close()};
}
function input(s,id,value){const e=s.d.getElementById(id);e.value=value;e.dispatchEvent(new s.w.Event('input'));return e}
function consent(s){for(const id of ['pdRegistrationConsent','pdObPhoneConsent'])s.d.getElementById(id).checked=true}
function valid(s){input(s,'pdObPassengerName','Test Passenger');input(s,'pdObPassengerPhone','+37060000000');consent(s)}
async function registration(){
 for(const lang of ['ru','en','lt']){
  const s=setup(false,false,lang);input(s,'pdObPassengerEmail','invalid');await s.w.pdRegisterPassengerTelegram();
  assert.equal(s.d.querySelector('#pdObStatus a')?.href,'https://t.me/EuroBalticTransferBot','Guest must receive Telegram entry before signup consent');
  assert.equal(s.calls.api.length,0);s.close();
 }
 const existing=setup(true,true);input(existing,'pdObPassengerEmail','overwrite@example.test');await existing.w.pdRegisterPassengerTelegram();
 assert.equal(existing.calls.complete,1);assert.equal(existing.calls.api.length,0,'Existing profile must not be overwritten');existing.close();
 const signup=setup(true);await signup.w.pdRegisterPassengerTelegram();assert.equal(signup.calls.telegram,0);
 signup.d.getElementById('pdRegistrationConsent').checked=true;await signup.w.pdRegisterPassengerTelegram();assert.equal(signup.calls.telegram,0,'Phone-sharing consent retained');
 consent(signup);await signup.w.pdRegisterPassengerTelegram();assert.equal(signup.calls.telegram,1);signup.close();
 for(const [id,value] of [['pdObPassengerPhone','abc'],['pdObPassengerPhone','+370+60000000'],['pdObPassengerName','   '],['pdObPassengerEmail','user@localhost']]){
  const s=setup(true);valid(s);input(s,id,value);await s.w.pdRegisterPassenger();assert.equal(s.calls.register,0,id);s.close();
 }
 const corrected=setup(true);valid(corrected);input(corrected,'pdObPassengerPhone','abc');await corrected.w.pdRegisterPassenger();input(corrected,'pdObPassengerPhone','+370 (600) 00000');input(corrected,'pdObPassengerEmail','new@example.test');await corrected.w.pdRegisterPassenger();
 assert.equal(corrected.calls.complete,1);assert.deepEqual(JSON.parse(JSON.stringify(corrected.calls.api.find(x=>x.body)?.body)),{email:'new@example.test',home_city:'Vilnius',preferences:'Quiet'});corrected.close();
 const pilot=setup(true);input(pilot,'pdObDriverName','Test Pilot');input(pilot,'pdObDriverPhone','abc');
 for(const id of ['pdObDriverCity','pdObDriverVehicle','pdObDriverYear','pdObDriverSeats','pdObDriverPlate'])pilot.d.getElementById(id).disabled=true;
 await pilot.w.pdRegisterDriver();assert.equal(pilot.calls.driver,0);input(pilot,'pdObDriverPhone','+37060000000');await pilot.w.pdRegisterDriver();assert.equal(pilot.calls.driver,1);pilot.close();
 console.log('PASS registration: RU/EN/LT guest launch, existing profile, separate consents, name/phone/email validation and correction, profile preservation, pilot phone');
}
async function notices(){
 for(const [status,payment_status,dialogs] of [['Подтверждена','Оплачено',0],['Подтверждена','Перевод на проверке',0],['Подтверждена','Криптоперевод на проверке',0],['Отменена','Не оплачено',0],['Выполнена','Не оплачено',0],['Подтверждена','Не оплачено',1]]){
  const dom=new JSDOM('<body></body>',{url:'https://private-drive.test',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;let poll;
  w.PD_LANG='ru';w.initData='FAKE';w.pdOnboardingUser={id:101,registered:true};w.admin=false;
  w.setTimeout=fn=>{poll=fn};w.setInterval=()=>{};
  w.api=async url=>url==='/api/passenger/notices'?{events:[{kind:'payment',key:'fixture',order_id:1,amount:'100'}]}:{status,payment_status,price:'125'};
  w.pdSimpleDialog=title=>{const d=w.document.createElement('dialog');d.append(title);w.document.body.append(d);return d};
  w.eval(source('pd_passenger_notices.js','pd-passenger-notices-v5.js'));await poll();
  assert.equal(w.document.querySelectorAll('dialog').length,dialogs,payment_status+' '+status);
  if(dialogs)assert.match(w.document.body.textContent,/125 €/,'Latest ledger amount replaces stale notice');w.close();
 }
 const dom=new JSDOM('<body></body>',{url:'https://private-drive.test',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;let poll;
 Object.assign(w,{PD_LANG:'ru',initData:'FAKE',pdOnboardingUser:{id:101,registered:true},admin:false,setTimeout:fn=>{poll=fn},setInterval:()=>{},api:async url=>{if(url.includes('/notices'))return {events:[{kind:'payment',key:'f',order_id:1}]};throw Error('offline')},pdSimpleDialog:()=>{throw Error('Must not show payment request without ledger')}});
 w.eval(source('pd_passenger_notices.js','pd-passenger-notices-v5.js'));await poll();assert.equal(w.document.querySelectorAll('dialog').length,0);w.close();
 console.log('PASS payment notices: paid, bank/crypto review, canceled/completed skipped; current amount used; provider/network failure does not request payment');
}
async function startRide(){
 for(const [status,allowed] of [['Оплачено',true],['Не оплачено',false],['Перевод на проверке',false],['Криптоперевод на проверке',false],['Ожидается оплата наличными',false]]){
  const dom=new JSDOM('<body></body>',{url:'https://private-drive.test',runScripts:'outside-only'}),w=dom.window;const calls=[];let gps=0;
  w.PD_LANG='ru';w.pdL=s=>s;w.setInterval=()=>{};w.setTimeout=()=>{};w.message=()=>{};
  Object.defineProperty(w.navigator,'geolocation',{value:{getCurrentPosition:ok=>{gps++;ok({coords:{latitude:54,longitude:25,accuracy:10}})},watchPosition:()=>123,clearWatch:()=>{}}});
  w.api=async(url,body)=>{calls.push({url,body});return url==='/api/driver/work'?{orders:[{id:24,payment_status:status}]}:{ok:true}};
  w.eval(source('pd_trip_runtime_v4.js','pd-trip-runtime-v4.js'));
  if(allowed){await w.pdStartRideV7(24);assert.equal(gps,1);assert(calls.some(x=>x.body?.action==='start'))}
  else{await assert.rejects(()=>w.pdStartRideV7(24),/оплата ещё не подтверждена/);assert.equal(gps,0);assert(!calls.some(x=>x.body?.action==='start'))}
  w.close();
 }
 console.log('PASS trip start UI: paid proceeds; unpaid/review/cash receipt states explained before GPS; no unpaid start request');
}
async function assignment(){
 const dom=new JSDOM('<body><div id="pdDriverApplicationsList"></div></body>',{url:'https://private-drive.test',runScripts:'outside-only'}),w=dom.window;let original=0,applications=0;
 w.PD_LANG='ru';w.pdL=s=>s;w.pdAssignPilot=async()=>{original++};w.go=()=>{};w.admin=true;w.setTimeout=()=>{};w.setInterval=()=>{};w.message=()=>{};
 w.api=async()=>({pilots:[]});w.pdSimpleDialog=title=>{const d=w.document.createElement('dialog');d.append(title);w.document.body.append(d);return d};
 w.HTMLDialogElement.prototype.close=function(){this.dispatchEvent(new w.Event('close'));this.remove()};w.pdLoadDriverApplications=async()=>{applications++};
 w.eval(source('pd_admin_console_v4.js','pd-admin-console-v4.js'));await w.pdAssignPilot(24);
 assert.match(w.document.body.textContent,/Нет одобренных пилотов/);assert.match(w.document.body.textContent,/Открыть заявки/);assert.equal(original,0);
 await w.document.querySelector('dialog button').onclick();assert(w.document.getElementById('pdPilotApplicationsDialogV4'));assert.equal(applications,1);
 w.api=async()=>({pilots:[{telegram_id:202}]});await w.pdAssignPilot(24);assert.equal(original,1);w.close();
 console.log('PASS pilot assignment UI: empty approved list explains card absence and links to applications; eligible pilots use existing assignment flow');
}
function timeDraft(){
 const dom=new JSDOM(html,{url:'https://private-drive.test/?lang=ru',runScripts:'outside-only'}),w=dom.window,d=w.document;
 const head=html.match(/<script>([\s\S]*?)<\/script>/)[1];w.eval(head);
 w.pdBootstrapDone=true;w.go=()=>{};w.pdbSummary=()=>{};w.pdRestoreStop=()=>{};
 w.sessionStorage.setItem('pdLanguageDraft',JSON.stringify({at:Date.now(),fields:{pdbDate:{value:'2026-12-10'},pdbTime:{value:'18:47'},pdbAgree:{checked:true},pdObPhoneConsent:{checked:true}},step:11}));
 Object.defineProperty(d,'readyState',{value:'complete',configurable:true});w.pdMaybeRestoreLanguageDraft();
 assert.equal(d.getElementById('pdbTime').value,'18:47');assert.equal(d.getElementById('pdbDate').value,'2026-12-10');assert.equal(d.getElementById('pdbAgree').checked,false);assert.equal(d.getElementById('pdObPhoneConsent').checked,false);w.close();
 console.log('PASS live snapshot language reload restores 18:47 and date; consent is requested again');
}
(async()=>{timeDraft();await registration();await notices();await startRide();await assignment();for(const file of fs.readdirSync(path.join(root,'public')).filter(f=>f.endsWith('.js')))new vm.Script(fs.readFileSync(path.join(root,'public',file),'utf8'));console.log('PASS all 13 downloaded public scripts parse')})().catch(e=>{console.error(e);process.exitCode=1});
