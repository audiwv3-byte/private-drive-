/* Tests real renderList() from pd_admin_console_v4.js with deferred API replies.
 * No server/user/order writes; only synthetic counters and filter events.
 */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const raw=fs.readFileSync('pd_admin_console_v4.js','utf8');
const from=raw.indexOf('async function renderList(append=false){');
const end=raw.indexOf('\nfunction formField(',from);
assert(from>=0&&end>from,'Exact renderList source function must exist');
const fn=raw.slice(from,end);
const isRealQueue=fn.includes('pendingRender')&&fn.includes('queueMicrotask');
assert(isRealQueue,'Busy request queue must exist');
const pools={};
class Node{
 constructor(){this.children=[];this.hidden=false;this.value='';this.dataset={};}
 replaceChildren(){this.children=[];}
 append(...items){this.children.push(...items);}
}
for(const id of ['pdAdminStatsV4','pdAdminMoreV4','pdAdminUpdatedV4','pdAdminStatusV4','pdAdminSearchV4','pdAdminDayV4'])
 pools[id]=new Node();
const list=new Node();
const pending=[];
const requests=[];
const api=(path)=>{requests.push(path);return new Promise(resolve=>pending.push(resolve))};
const constants=[
 'var root={hidden:false},list=this.list;',
 "var filter='all',query='',day='',cursor=null,selected=null,busy=false,pendingRender=null,lastLoaded=0;",
 'const $id=id=>this.pools[id];',
 'const pdL=s=>s;',
 "const text=(ru,en,lt)=>ru;",
 "const euros=n=>n+' €';",
 "const clock=n=>n+'s';",
 "const message=()=>{};",
 'const el=(tag,content)=>{const o={tag,textContent:String(content||""),children:[],append(...xs){this.children.push(...xs);}};return o};',
 'const btn=(label,fn)=>({label,onclick:fn,dataset:{},append(){},className:""})',
 'const api=this.api,queueMicrotask=this.queueMicrotask;',
 fn,
 'this.control={renderList,stats:()=>this.pools.pdAdminStatsV4.children,filter:()=>filter,busy:()=>busy};'
].join('\n');
const ctx={list,pools,api,Date,URLSearchParams,queueMicrotask,console};
vm.createContext(ctx);
vm.runInContext(constants,ctx);
function respond(status){
 const next=pending.shift();
 assert(next,'Expected exactly one pending synthetic API call');
 next({orders:[],counts:{'Новая':2,'Подтверждена':3,'В пути':4},unpaid:1,next_before:null});
}
function delay(){return new Promise(resolve=>setImmediate(resolve));}
async function test(){
 const initial=ctx.control.renderList();
 assert.equal(requests.length,1);
 respond();await initial;
 assert.equal(ctx.control.stats().length,4);
 const second=ctx.control.renderList();
 assert.equal(requests.length,2);
 const newButton=ctx.control.stats()[0];
 newButton.onclick();
 assert.equal(ctx.control.filter(),'Новая');
 assert.equal(requests.length,2,'new filter must be queued, not dropped');
 respond();await second;await delay();
 assert.equal(requests.length,3,'queued New filter must fetch');
 assert(requests[2].includes('status=%D0%9D%D0%BE%D0%B2%D0%B0%D1%8F'));
 respond();await delay();
 assert.equal(ctx.control.busy(),false);
 console.log('PASS NEW_FILTER_REQUEST_NOT_DROPPED_DURING_BUSY');
 const fourth=ctx.control.renderList();
 const runningButton=ctx.control.stats()[2];
 runningButton.onclick();
 assert.equal(requests.length,4);
 respond();await fourth;await delay();
 assert.equal(requests.length,5);
 assert(requests[4].includes('status=%D0%92+%D0%BF%D1%83%D1%82%D0%B8'));
 respond();await delay();
 assert.equal(ctx.control.filter(),'В пути');
 console.log('PASS IN_PROGRESS_FILTER_REQUEST_NOT_DROPPED_DURING_BUSY');
 assert.equal(ctx.control.stats().length,4);
 console.log('ADMIN_STATUS_FILTER_SYNTHETIC_TESTS_PASS');
}
test().catch(e=>{console.error(e);process.exit(1)});
