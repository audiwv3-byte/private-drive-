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
check(owner, 'driver', {passengerView: false, adminControls: false, pilotControls: false});
check(pilot, 'driver', {passengerView: false, adminControls: false, pilotControls: true});
check(pilot, 'client', {passengerView: true, adminControls: false, pilotControls: false});
assert.equal(elements.get('pdPilotBack').hidden, true);
check(applicant, '', {passengerView: false, adminControls: false, pilotControls: true});
// Changing to an ordinary passenger cannot retain another role's controls.
check(passenger, '', {passengerView: true, adminControls: false, pilotControls: false});
assert.ok(!html.includes('onclick="pdStartDriverRegistration()">Регистрация водителя</button>'));
assert.ok(html.includes('body:not(.pd-role-admin) #pdRoleBar'));
const fs2 = require('node:fs');
const pilotCabinet = fs2.readFileSync('pd_pilot_cabinet_v4.js','utf8');
const runtime = fs2.readFileSync('pd_trip_runtime_v4.js','utf8');
const fullscreen = fs2.readFileSync('miniapp/static/pd-pilot-fullscreen-v5.js','utf8');
for(const src of [pilotCabinet,runtime,fullscreen]) new vm.Script(src);
assert.ok(!html.includes('id="pdPilotPassenger"'), 'pilot passenger switch removed');
assert.ok(html.includes('body.pd-pilot-cabinet #pdRoleBar'), 'role selector hidden in pilot mode');
assert.ok(html.includes('body.pd-pilot-cabinet #mainNav'), 'passenger nav hidden in pilot mode');
assert.ok(pilotCabinet.includes('openPilotTrip(order)'), 'pilot work trip clickable');
assert.ok(pilotCabinet.includes('Включить GPS для работы'), 'single work GPS entry');
assert.ok(runtime.includes('label(\'Изменить маршрут\''), 'pilot inline route change');
assert.ok(runtime.includes("r.stop_active?'resume':'pause'"), 'pilot stop/resume buttons');
assert.ok(runtime.includes("map.on('dblclick',expand)"), 'double click map expansion');
assert.ok(fullscreen.includes("Изменить маршрут")&&fullscreen.includes("Остановка")&&fullscreen.includes("Завершить поездку"), 'fullscreen controls');
console.log('PASS: pilot cabinet map click, stop/resume/route buttons, fullscreen double-tap, single work GPS and role isolation');
const tips = fs.readFileSync('pd_tips_widget.js','utf8');
new vm.Script(tips);
assert.ok(tips.includes("{id:'paysera',label:'Paysera'}"), 'Paysera displayed as first top-level choice');
assert.ok(tips.includes("{id:'swedbank',label:'Swedbank'}"), 'Swedbank displayed as second top-level choice');
assert.ok(tips.includes("{id:'crypto',label:t('Криптовалюта'"), 'cryptocurrency displayed as third top-level choice');
assert.ok(tips.includes("for(const ticker of ['USDC','BTC','ETH'])"), 'crypto options nested behind crypto selection');
assert.ok(tips.includes("if(id==='crypto'){"), 'crypto choices not offered at top level');
assert.ok(!tips.includes("type:'cash'"), 'cash is not a top-level tip method');
const tipInjector = fs.readFileSync('pd_tips_widget.py','utf8');
assert.ok(tipInjector.includes('pd-tips-widget.js?v=20261029-tips-three-methods-v4'), 'new tip widget cache version');
console.log('PASS: tips top level is Paysera, Swedbank, Cryptocurrency; USDC/BTC/ETH nested; JS syntax valid');
console.log('PASS: passenger, administrator, pilot and applicant roles; passenger mode hides work controls; stale role controls cleared; inline scripts compile');
