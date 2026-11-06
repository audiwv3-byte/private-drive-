'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('miniapp/templates/index.html','utf8');
const scripts=[html,...['pd_trip_runtime_v4.js','pd_pilot_cabinet_v4.js','pd_admin_console_v4.js','pd_prepayment_v3.js','pd_invoice_v2.js'].map(f=>fs.readFileSync(f,'utf8'))].join('\n');
const names=[...new Set([...html.matchAll(/\bonclick="([^"]+)"/g)].map(m=>/^\s*([A-Za-z_$][\w$]*)\s*\(/.exec(m[1])?.[1]).filter(Boolean))];
assert.ok(names.length>=45,'Button inventory shrank');
for(const name of names)assert.match(scripts,new RegExp('(?:function\\s+|(?:const|let|var)\\s+|window\\.)'+name+'\\b|\\b'+name+'\\s*=\\s*(?:async\\s*)?function'),'Missing handler '+name);
for(const label of ['pdbSendOrder()','pdbCalculate()','pdbLocate(','pdEnterPilot()','pdSwitchTab(','pdBankConfirm(','pdAssignPilot('])assert.ok(html.includes(label),'Missing control '+label);
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))if(m[1].trim())new vm.Script(m[1].replace(/\{\{[\s\S]*?\}\}/g,'null'));
console.log('PASS HTML: '+names.length+' handlers resolve, key controls wired, inline JS parses');

function element(tag='div'){
 const classes=new Set();
 return {tag,children:[],dataset:{},style:{},textContent:'',id:'',
  classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},
  append(...c){this.children.push(...c)},replaceChildren(...c){this.children=[...c]},
  addEventListener(type,cb){(this.events??={})[type]=cb},close(){this.events?.close?.()}};
}
const requests=[],messages=[],cleared=[];
const document={hidden:false,listeners:{},createElement:element,getElementById:()=>null,querySelectorAll:()=>[],addEventListener(k,cb){this.listeners[k]=cb}};
const state={status:'Подтверждена',role:'pilot',arrived_at:null,started_at:null,server_now:1700000000,lat:null,lon:null,accuracy:0,extras:[],final_cents:null,base_cents:10000,wait_cents:0,wait_accepted_at:1700000000,capture:null,card_capture_available:false};
let watchCallback,watchId=0,dialog;
const navigator={geolocation:{watchPosition(ok){watchCallback=ok;return ++watchId},clearWatch(id){cleared.push(id)}}};
const window={PD_LANG:'ru',Telegram:{WebApp:{enableClosingConfirmation(){},disableClosingConfirmation(){}}},addEventListener(){},L:null};
const api=async(path,data)=>{
 requests.push({path,data});
 if(/^\/api\/trip\/\d+$/.test(path))return {...state};
 if(path.endsWith('/action')){
  if(data.action==='arrive')state.arrived_at=1700000000;
  if(data.action==='start'){state.status='В пути';state.started_at=1700000100;}
  if(data.action==='finish'){state.status='Выполнена';state.final_cents=10000;}
  return {ok:true};
 }
 if(path.endsWith('/location'))return {ok:true};
 throw Error('Unexpected mock API '+path);
};
const context={window,document,navigator,api,crypto:{randomUUID:()=> 'test-uuid'},Date,console,Math,Number,String,setInterval(){},setTimeout(){},message:s=>messages.push(s),pdSimpleDialog(){dialog=element('dialog');return dialog},pdCheckTripCompletion(){},initData:'',pdRegistered:false};
vm.createContext(context);vm.runInContext(fs.readFileSync('pd_trip_runtime_v4.js','utf8'),context);
const buttons=()=>{const out=[];const scan=n=>{if(n.tag==='button')out.push(n);for(const c of n.children||[])scan(c)};scan(dialog);return out};
const button=label=>buttons().find(n=>n.textContent.includes(label));
async function click(label){const b=button(label);assert.ok(b,'Missing button '+label);await b.onclick();assert.equal(b.disabled,false,'Button remained disabled '+label)}
(async()=>{
 await window.pdOpenLiveTripV4(42);
 assert.ok(button('Прибыл'));assert.ok(button('Передавать мою геопозицию'));assert.equal(button('Поездка завершена'),undefined);
 await click('Передавать мою геопозицию');
 assert.equal(watchId,1);assert.ok(button('Остановить передачу геопозиции'));
 await watchCallback({coords:{latitude:54.6872,longitude:25.2797,accuracy:8}});
 const loc=requests.filter(r=>r.path.endsWith('/location'));
 assert.equal(loc.length,1);assert.deepEqual(JSON.parse(JSON.stringify(loc[0].data)),{lat:54.6872,lon:25.2797,accuracy:8});
 await click('Остановить передачу геопозиции');
 assert.deepEqual(cleared,[1]);assert.ok(button('Передавать мою геопозицию'));
 await click('Прибыл');assert.ok(button('Начать поездку'));
 await click('Начать поездку');assert.ok(button('Поездка завершена'));assert.equal(button('Прибыл'),undefined);
 await click('Поездка завершена');assert.equal(state.status,'Выполнена');assert.equal(button('Передавать мою геопозицию'),undefined);
 assert.deepEqual(requests.filter(r=>r.path.endsWith('/action')).map(r=>r.data.action),['arrive','start','finish']);
 console.log('PASS trip: arrive, start, finish; conditional buttons');
 console.log('PASS GPS: enable, mock coordinates, disable, restore button, hide on completed');
 state.role='passenger';state.status='Подтверждена';state.arrived_at=null;state.started_at=null;state.final_cents=null;
 await window.pdOpenLiveTripV4(42);
 assert.equal(button('Передавать мою геопозицию'),undefined);assert.equal(button('Прибыл'),undefined);assert.equal(button('Поездка завершена'),undefined);
 console.log('PASS passenger: pilot GPS and action controls hidden');
 state.role='pilot';
 await window.pdOpenLiveTripV4(42);await click('Передавать мою геопозицию');
 const before=cleared.length;document.hidden=true;document.listeners.visibilitychange();
 assert.equal(cleared.length,before+1,'GPS watch did not stop on background');
 document.hidden=false;
 await window.pdOpenLiveTripV4(42);
 await click('Передавать мою геопозицию');
 const beforeClose=cleared.length;
 dialog.close();
 assert.equal(cleared.length,beforeClose+1,'GPS watch did not stop on dialog close');
 console.log('PASS GPS privacy: background and dialog close stop tracking');
 assert.deepEqual(messages,[]);
})().catch(e=>{console.error(e);process.exitCode=1});
