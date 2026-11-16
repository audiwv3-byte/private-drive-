/* Offline cockpit tests: fake DOM, fake Leaflet, fake GPS, fake API.
No browser network, customer data, real geolocation, bookings or payments.
*/
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('experimental/pd_pilot_cockpit_staged.js','utf8');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};this.attrs={};this.hidden=false;this.parentNode=null;this.className='';this.id='';}
 append(...items){for(const c of items){c.parentNode=this;this.children.push(c);}}
 replaceChildren(...items){this.children=[];this.append(...items);}
 removeChild(child){this.children=this.children.filter(x=>x!==child);child.parentNode=null;}
 setAttribute(k,v){this.attrs[k]=v;}
 set innerHTML(x){if(x!=='')throw Error('Unsafe markup');this.children=[];}
}
const dummyDocument={hidden:false,createElement:tag=>new Element(tag)};
const root=new Element('main');
const passport=new Element('section');passport.id='passenger-home';
const admin=new Element('section');admin.id='admin-home';root.append(passport,admin);
const timers=new Map();let nextTimer=0;
const mockWindow={setInterval:(fn)=>{const n=++nextTimer;timers.set(n,fn);return n;},clearInterval:n=>timers.delete(n)};
let createdMaps=0,moved=0,setPosition=0,removed=0,latestMarker=null,dragHandler=null;
const leaflet={
 map:()=>{createdMaps++;return{
   setView(){return this;},panTo(){moved++;return this;},invalidateSize(){},on(name,cb){if(name==='dragstart')dragHandler=cb;return this;},remove(){removed++;}
 }},
 tileLayer:()=>({addTo(){}}),
 marker:()=>{latestMarker={setLatLng(){setPosition++;},addTo(){return this;}};return latestMarker;}
};
let nextGps=0,clearCount=0,gpsCallbacks={};
const geo={watchPosition(fn,err){gpsCallbacks[0]=fn;gpsCallbacks[1]=err;return ++nextGps;},clearWatch(){clearCount++;}};
let requests=[],workOrders=[];
const api=async(path,data)=>{
 requests.push({path,data});
 if(path==='/api/driver/work')return{orders:workOrders};
 return{ok:true};
};
let opened=[];
const context={window:{},globalThis:{},Date,Number,encodeURIComponent,console};
vm.createContext(context);vm.runInContext(source,context,{filename:'pd_pilot_cockpit_staged.js'});
const impl=context.window.PD_PILOT_COCKPIT_STAGED;
assert(impl);
const action=(state)=>impl.nextAction(state);
assert.equal(action({status:'Подтверждена',arrived_at:null}),'arrive');
assert.equal(action({status:'Подтверждена',arrived_at:123}),'start');
assert.equal(action({status:'В пути'}),'finish');
assert.equal(action({status:'Новая'}),null);
assert.equal(impl.pickActive([{status:'Отменена'},{id:41,status:'Подтверждена'}]).id,41);
assert.equal(impl.coords(91,40),false);assert.equal(impl.coords(54.68,25.27),true);
console.log('PASS PILOT_STATE_ACTIONS_AND_COORDS');
async function test(){
 const cockpit=impl.make({api,leaflet,document:dummyDocument,window:mockWindow,geolocation:geo,lang:'ru',openNavigation:u=>opened.push(u)});
 assert.equal(cockpit.mount(root,false),false);
 assert.equal(createdMaps,0);
 assert.equal(root.children.length,2);
 console.log('PASS UNAPPROVED_PILOT_NO_MAP_OR_TRIPS');
 workOrders=[{id:32,status:'Подтверждена',origin:'Vilnius',destination:'Kaunas',arrived_at:null}];
 assert.equal(cockpit.mount(root,true),true);
 await new Promise(res=>setImmediate(res));
 assert.equal(createdMaps,1);
 assert.equal(root.children.length,3);
 assert.equal(root.children[0],passport);assert.equal(root.children[1],admin);
 assert.equal(cockpit.state().hasMap,true);
 assert.equal(cockpit.state().selectedOrder,32);
 console.log('PASS FULLSCREEN_COCKPIT_MOUNTS_WITHOUT_OTHER_ROLE_MODIFICATIONS');
 cockpit.startGps();
 assert.equal(cockpit.state().gpsEnabled,true);
 const gpsButtons=root.children[2].children[2].children[1].children;
 assert.equal(gpsButtons[0].hidden,true);
 assert.equal(gpsButtons[1].hidden,false);
 gpsCallbacks[0]({coords:{latitude:54.68,longitude:25.27,accuracy:8}});
 await new Promise(res=>setImmediate(res));
 assert.equal(requests.some(r=>r.path==='/api/trip/32/location'),true);
 gpsCallbacks[0]({coords:{latitude:54.681,longitude:25.271,accuracy:8}});
 await new Promise(res=>setImmediate(res));
 assert.equal(createdMaps,1,'map should not be recreated');
 assert.equal(setPosition>=1,true,'marker should move in place');
 const firstMove=moved;
 dragHandler();
 gpsCallbacks[0]({coords:{latitude:54.682,longitude:25.272,accuracy:5}});
 await new Promise(res=>setImmediate(res));
 assert.equal(moved,firstMove,'manual map pan should suspend auto-follow');
 assert.equal(cockpit.state().followGps,false);
 const followButton=root.children[2].children[2].children[1].children[2];
 followButton.onclick();
 assert.equal(cockpit.state().followGps,true);
 assert.equal(moved,firstMove+1,'follow me should immediately recenter');
 console.log('PASS GPS_BUTTON_HIDES_AND_MAP_MARKER_UPDATES_IN_PLACE');
 cockpit.stopGps();
 assert.equal(cockpit.state().gpsEnabled,false);
 assert.equal(clearCount>=1,true);
 assert.equal(gpsButtons[0].hidden,false);
 console.log('PASS GPS_STOP_RESTORES_BUTTON_AND_RELEASES_WATCH');
 cockpit.stopGps();
 cockpit.dispose();
 assert.equal(removed,1);
 assert.equal(timers.size,0);
 assert.equal(root.children.length,2);
 assert.equal(root.children[0],passport);assert.equal(root.children[1],admin);
 console.log('PASS DISPOSE_CLEANS_MAP_TIMERS_AND_PRESERVES_PASSENGER_ADMIN');
 console.log('PILOT_COCKPIT_ISOLATED_TESTS_PASSED');
}
test().catch(e=>{console.error(e);process.exit(1)});
