/* Experimental cockpit integration adapter. Appended AFTER original pilot JS.
 * No server mutations, no passenger/dispatcher side-effects.
 * Must not enable for applicant without verified pilot_access.
 */
(function(root){
'use strict';
if(!root.PD_PILOT_COCKPIT_STAGED)return;
const doc=root.document;
if(!doc||typeof root.api!=='function'||!root.L)return;
const baseEnter=root.pdEnterPilot,basePassenger=root.pdPilotPassenger;
if(typeof baseEnter!=='function'||typeof basePassenger!=='function')return;
let cockpit=null,active=false;
const approved=()=>Boolean(root.pdOnboardingUser?.pilot_access) && !Boolean(root.pdOnboardingUser?.admin);
const pendingPilot=()=>Boolean(root.pdOnboardingUser?.driver_application) && !approved();
function enable(){
 if(!approved())return false;
 const host=doc.body;
 if(!host||!doc.getElementById('pdPilotWork'))return false;
 if(!cockpit){
  cockpit=root.PD_PILOT_COCKPIT_STAGED.make({
   api:(path,data)=>root.api(path,data),
   leaflet:root.L,document:doc,window:root,geolocation:root.navigator?.geolocation,
   lang:root.PD_LANG||'ru',
   openNavigation:url=>root.open(url,'_blank','noopener,noreferrer'),
   // Existing app's stop/extra workflow is reused, never duplicated.
   onStop:(id)=>root.pdOpenLiveTripV4?.(id)
  });
 }
 if(!cockpit.mount(host,true))return false;
 doc.body.classList.add('pd-pilot-cockpit-on');
 active=true;
 return true;
}
function leave(){
 if(cockpit)cockpit.unmount();
 doc.body?.classList.remove('pd-pilot-cockpit-on');
 active=false;
}
root.pdEnterPilot=function(){
 // Approved pilot: retain original role guard and setup, but overlay the
 // cockpit on the pilot-only visual route. Applicants keep original UI.
 const ret=baseEnter.apply(this,arguments);
 if(approved())enable();
 else leave();
 return ret;
};
root.pdPilotPassenger=function(){
 leave();
 return basePassenger.apply(this,arguments);
};
root.PD_COCKPIT_ADAPTER_STAGED={
 enable,leave,approved,
 state:()=>({mounted:active,approved:approved(),applicant:pendingPilot()})
};
// Original pilot-cabinet script may have entered pilot before this adapter
// was loaded. Join it without disturbing passenger/admin users.
if(approved()&&doc.getElementById('pdPilotWork')&&!doc.getElementById('pdPilotWork').classList.contains('hidden')){
 enable();
}
})(window);
