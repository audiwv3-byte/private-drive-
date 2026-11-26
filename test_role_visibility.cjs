const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('miniapp/templates/index.html', 'utf8');
for (const id of ['pdObRole','pdObDriver','pdRoleBar','adminNav','pdPilotWork','step10','step13']) {
  assert.ok(!html.includes('id="' + id + '"'), id);
}
for (const id of ['pdObLanguage','pdObPassenger','pdbSend','step8','step9','step14']) {
  assert.ok(html.includes('id="' + id + '"'), id);
}
assert.doesNotMatch(html, /<script src="[^"]*(?:pilot-cabinet|admin-console)/);
const storage = new Map();
const context = {
  window: {PD_LANG:'ru'}, localStorage: {getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
  pdShowOnboarding(stage){context.screen=stage}, pdHideOnboarding(){context.screen='booking'},
};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function pdChooseInitialLanguage('),
  html.indexOf('async function pdCompletePassengerRegistration(')), context);
context.pdOnboardingStart(null);
assert.equal(context.screen,'language');
context.pdChooseInitialLanguage('ru');
assert.equal(context.screen,'passenger');
for (const flags of [{},{admin:true},{pilot_access:true},{driver_application:{status:'pending'}}]) {
  context.pdOnboardingStart({...flags,registered:true,phone:'5551234',name:'QA'});
  assert.equal(context.screen,'booking');
  context.pdOnboardingStart(flags);
  assert.equal(context.screen,'passenger');
}
console.log('PASS passenger entry for new, returning, admin, pilot and applicant accounts');
