/* Production-version Mini App test: all state and location calls mocked, no network. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('miniapp/templates/index.html','utf8');
const scripts=[html,...['pd_trip_runtime_v4.js','pd_pilot_cabinet_v4.js','pd_admin_console_v4.js','pd_prepayment_v3.js','pd_invoice_v2.js'].map(f=>fs.readFileSync(f,'utf8'))].join('\n');
const names=[...new Set([...html.matchAll(/\bonclick="([^"]+)"/g)].map(m=>/^\s*([A-Za-z_$][\w$]*)\s*\(/.exec(m[1])?.[1]).filter(Boolean))];
assert.ok(names.length>=45);
for(const name of names)assert.match(scripts,new RegExp('(?:function\\s+|(?:const|let|var)\\s+|window\\.)'+name+'\\b|\\b'+name+'\\s*=\\s*(?:async\\s*)?function'),'Missing handler '+name);
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))if(m[1].trim())new vm.Script(m[1].replace(/\{\{[\s\S]*?\}\}/g,'null'));
console.log('PASS production HTML: '+names.length+' inline handlers resolve and scripts parse');
function element(tag='div'){const cs=new Set();return {tag,children:[],dataset:{},style:{},textContent:'',id:'',
 classList:{add:x=>cs.add(x),remove:x=>cs.delete(x),contains:x=>cs.has(x),toggle(x,v){if(v??!cs.has(x))cs.add(x);else cs.delete(x)}},
 append(...c){this.children.push(...c)},replaceChildren(...c){this.children=[...c]},addEventListener(t,cb){(this.events??={})[t]=cb},close(){this.events?.close?.()}}}
const events=[],errors=[],cleared=[],storage=new Map();
const ls={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
let dialog=null,watchCallback,watchId=0;
const coordinates={latitude:54.6872,longitude:25.2797,accuracy:8};
const document={hidden:false,listeners:{},createElement:element,getElementById:()=>null,querySelectorAll:()=>[],addEventListener(k,cb){this.listeners[k]=cb}};
const navigator={geolocation:{
 getCurrentPosition(ok){ok({coords:coordinates})},
 watchPosition(ok){watchCallback=ok;return ++watchId},
 clearWatch(id){cleared.push(id)}
}};
const window={PD_LANG:'ru',Telegram:{WebApp:{enableClosingConfirmation(){},disableClosingConfirmation(){}}},addEventListener(){},L:null,localStorage:ls};
const state={status:'Подтверждена',role:'pilot',departed_at:null,arrived_at:null,started_at:null,ended_at:null,stop_started_at:null,server_now:1700000000,lat:null,lon:null,accuracy:0,extras:[],final_cents:null,base_cents:10000,wait_cents:0,wait_accepted_at:1700000000,stop_accepted_at:1700000000,capture:null,card_capture_available:false};
async function api(path,data){events.push({path,data});
 if(/^\/api\/trip\/\d+$/.test(path))return {...state};
 if(path.endsWith('/depart')){state.departed_at=1700000000;return {ok:true}}
 if(path.endsWith('/location'))return {ok:true};
 if(path.endsWith('/action')){const a=data.action;
  if(a==='arrive')state.arrived_at=1700000030;
  if(a==='start'||a==='recover_start'){state.status='В пути';state.started_at=1700000100}
  if(a==='stop_start')state.stop_started_at=1700000120;
  if(a==='stop_end')state.stop_started_at=null;
  if(a==='finish'){state.status='Выполнена';state.ended_at=1700000300;state.final_cents=10000}
  return {ok:true};
 }
 throw Error('Unexpected mock API '+path);
}
const ctx={window,document,navigator,localStorage:ls,sessionStorage:ls,api,
 crypto:{randomUUID:()=> 'mock-uuid'},Date,console,Math,Number,String,JSON,
 setInterval(){},setTimeout(){},message:s=>errors.push(s),
 pdSimpleDialog(){dialog=element('dialog');return dialog},pdCheckTripCompletion(){},initData:'',pdRegistered:false};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('pd_trip_runtime_v4.js','utf8'),ctx);
function buttons(){const out=[];function scan(n){if(!n)return;if(n.tag==='button')out.push(n);for(const c of n.children||[])scan(c)}scan(dialog);return out}
function button(t){return buttons().find(x=>x.textContent.includes(t))}
async function click(t){const b=button(t);assert.ok(b,'Button not shown: '+t+'; visible: '+buttons().map(x=>x.textContent).join('|'));await b.onclick();assert.equal(b.disabled,false)}
(async()=>{
 await window.pdOpenLiveTripV4(42);
 assert.ok(button('В пути к пассажиру'),'Missing pickup departure');
 assert.equal(button('Прибыл'),undefined,'Arrived shown before departure');
 await click('В пути к пассажиру');
 assert.ok(events.some(x=>x.path.endsWith('/depart')),'Departure API not called');
 assert.ok(watchId>=1,'Pickup departure did not begin GPS');
 assert.ok(button('Прибыл'),'Arrival absent after departure');
 assert.ok(typeof watchCallback==='function');
 await watchCallback({coords:coordinates});
 assert.ok(events.some(x=>x.path.endsWith('/location')),'Mock GPS coordinates not forwarded');
 await click('Прибыл');
 assert.ok(button('В путь'),'Start missing after arrival');
 await click('В путь');
 assert.equal(state.status,'В пути','Start did not change mock state');
 assert.ok(button('Остановка'),'Stop absent during trip');
 await click('Остановка');
 assert.ok(button('Продолжить поездку'),'Resume absent while stopped');
 await click('Продолжить поездку');
 assert.equal(state.stop_started_at,null);
 console.log('PASS production pilot: pickup departure, arrived, start, stop, resume');
 assert.ok(events.some(x=>x.path.endsWith('/action')&&x.data.action==='start'));
 assert.ok(events.some(x=>x.path.endsWith('/action')&&x.data.action==='stop_start'));
 assert.ok(events.some(x=>x.path.endsWith('/action')&&x.data.action==='stop_end'));
 console.log('PASS production GPS: permission, watch, sample coordinates');
 const before=cleared.length;dialog.close();
 assert.ok(cleared.length>before,'Close did not clear GPS');
 console.log('PASS production GPS: close trip dialog cancels watch');
 state.role='passenger';state.status='Подтверждена';
 await window.pdOpenLiveTripV4(42);
 assert.equal(button('Прибыл'),undefined);
 assert.equal(button('Остановка'),undefined);
 assert.equal(button('Продолжить поездку'),undefined);
 console.log('PASS production passenger: pilot controls not shown');
 assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1});
