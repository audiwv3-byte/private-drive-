const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('miniapp/templates/index.html', 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
  if (match[1].trim()) new vm.Script(match[1].replace(/\{\{[\s\S]*?\}\}/g, 'null'));
}
const elements = new Map();
function element() {
  const names = new Set();
  return {hidden: false, classList: {
    add: value => names.add(value),
    contains: value => names.has(value),
    toggle(value, enabled) { if (enabled) names.add(value); else names.delete(value); },
  }};
}
for (const id of ['pdRoleBar', 'adminNav', 'pdPilotBack']) elements.set(id, element());
const body = element(); body.dataset = {};
const context = {window: {}, document: {body}, $: id => elements.get(id)};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function pdRoleVisibility('), html.indexOf('function pdShowOnboarding(')), context);
const passenger = {registered: true, admin: false, pilot_access: false};
const pilot = {registered: true, admin: false, pilot_access: true};
const owner = {registered: true, admin: true, pilot_access: false};
const applicant = {registered: false, admin: false, driver_application: {status: 'pending'}};
function check(user, view, expected) {
  const role = context.pdApplyRoleAccess(user, view);
  assert.deepEqual(JSON.parse(JSON.stringify(role)), expected);
  assert.equal(elements.get('pdRoleBar').hidden, !expected.adminControls);
  assert.equal(elements.get('adminNav').hidden, !expected.adminControls);
  assert.equal(body.classList.contains('pd-passenger-view'), expected.passengerView);
  assert.equal(body.classList.contains('pd-role-pilot'), expected.pilotControls);
}
check(null, '', {passengerView: false, adminControls: false, pilotControls: false});
check(passenger, '', {passengerView: true, adminControls: false, pilotControls: false});
check(owner, 'admin', {passengerView: false, adminControls: true, pilotControls: false});
check(owner, 'client', {passengerView: true, adminControls: false, pilotControls: false});
check(pilot, 'driver', {passengerView: false, adminControls: false, pilotControls: true});
check(pilot, 'client', {passengerView: true, adminControls: false, pilotControls: false});
assert.equal(elements.get('pdPilotBack').hidden, true);
check(applicant, '', {passengerView: false, adminControls: false, pilotControls: true});
// Changing to an ordinary passenger cannot retain another role's controls.
check(passenger, '', {passengerView: true, adminControls: false, pilotControls: false});
assert.ok(!html.includes('onclick="pdStartDriverRegistration()">Регистрация водителя</button>'));
assert.ok(html.includes('body:not(.pd-role-admin) #pdRoleBar'));
console.log('PASS: passenger, administrator, pilot and applicant roles; passenger mode hides work controls; stale role controls cleared; inline scripts compile');
