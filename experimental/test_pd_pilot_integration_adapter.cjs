/* Cockpit integration adapter tests; simulate approved pilot/applicant/admin.
 * No real browser/requests and no production file updates.
 */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('experimental/pd_pilot_cockpit_adapter_staged.js','utf8');
class El {
 constructor(hidden=false){this.hidden=hidden;this.classList={current:new Set(hidden?['hidden']:[]),
  add:s=>this.classList.current.add(s),remove:s=>this.classList.current.delete(s),
  contains:s=>this.classList.current.has(s)}}
}
function build(kind){
 let called={enter:0,passenger:0,mount:0,unmount:0,open:0};
 const target=new El(false);
 const doc={body:{classList:new El().classList},getElementById:id=>id==='pdPilotWork'?target:null};
 const obj={
  window:null, document:doc,PD_LANG:'ru',
  api:async()=>({orders:[]}),L:{},navigator:{geolocation:{}},
  pdEnterPilot:()=>{called.enter++},
  pdPilotPassenger:()=>{called.passenger++},
  PD_PILOT_COCKPIT_STAGED:{make:()=>({
     mount:(host,approved)=>{assert.strictEqual(host,doc.body);assert(approved);called.mount++;return true},
     unmount:()=>called.unmount++
  })},
  open:()=>called.open++,
  pdOpenLiveTripV4:()=>{}
 };
 obj.pdOnboardingUser=kind==='approved'?{pilot_access:true,admin:false}:
   kind==='applicant'?{pilot_access:false,driver_application:{status:'pending'}}:
   kind==='admin'?{pilot_access:true,admin:true}:
   {pilot_access:false,registered:true};
 obj.window=obj;
 vm.createContext(obj);vm.runInContext(src,obj,{filename:'pilot-cockpit-adapter.js'});
 return {obj,doc,called,target};
}
let approved=build('approved');
assert.strictEqual(approved.called.mount,1);
assert(approved.doc.body.classList.contains('pd-pilot-cockpit-on'));
approved.obj.pdPilotPassenger();
assert.strictEqual(approved.called.unmount,1);
assert(!approved.doc.body.classList.contains('pd-pilot-cockpit-on'));
assert.strictEqual(approved.called.passenger,1);
approved.obj.pdEnterPilot();
assert.strictEqual(approved.called.enter,1);
assert.strictEqual(approved.called.mount,2);
console.log('PASS APPROVED_PILOT_ENTER_LEAVE_HOOK');
let applicant=build('applicant');
assert.strictEqual(applicant.called.mount,0);
applicant.obj.pdEnterPilot();
assert.strictEqual(applicant.called.mount,0);
assert(!applicant.doc.body.classList.contains('pd-pilot-cockpit-on'));
console.log('PASS UNAPPROVED_APPLICANT_SEES_EXISTING_APPLICATION_FLOW');
for(const kind of ['admin','passenger']){
 let e=build(kind);
 e.obj.pdEnterPilot();
 assert.strictEqual(e.called.mount,0);
 assert(!e.doc.body.classList.contains('pd-pilot-cockpit-on'));
 e.obj.pdPilotPassenger();
 assert.strictEqual(e.called.passenger,1);
 console.log('PASS '+kind.toUpperCase()+'_UI_UNTOUCHED');
}
const css=fs.readFileSync('experimental/pd_pilot_cockpit_staged.css','utf8');
assert(css.includes('height:100dvh'));
assert(css.includes('env(safe-area-inset-bottom'));
assert(css.includes('body.pd-pilot-cockpit-on'));
assert(!css.includes('body:not('));
console.log('PASS PILOT_SCOPED_CSS_MOBILE_SAFE_AREA');
console.log('PILOT_INTEGRATION_ADAPTER_SYNTHETIC_PASS');
