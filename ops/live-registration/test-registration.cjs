const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const source = fs.readFileSync(process.env.PD_REGISTRATION_SCRIPT || path.join(__dirname, 'pd-registration.js'), 'utf8');
const fixture = fs.readFileSync(path.join(__dirname, '../../miniapp/templates/index.html'), 'utf8');

function setup({signed = false, registered = false, lang = 'ru'} = {}) {
  const dom = new JSDOM(fixture, {url: 'https://private-drive.test/', runScripts: 'outside-only'});
  const w = dom.window, d = w.document;
  const calls = {signup: 0, telegram: 0, launch: 0, completed: 0, driver: 0, api: []};
  w.PD_LANG = lang;
  w.pdOnboardingUser = {registered};
  w.initData = signed ? 'TEST_ONLY' : '';
  w.pdSwitchLanguage = () => {};
  w.pdShowOnboarding = stage => {
    d.getElementById('pdObPassenger').classList.toggle('hidden', stage !== 'passenger');
  };
  w.pdCompletePassengerRegistration = async () => { calls.completed++; };
  w.api = async (url, body) => {
    calls.api.push({url, body});
    return {profile: {email: 'existing@example.test', home_city: 'Vilnius', preferences: 'Quiet'}};
  };
  w.pdRegisterPassenger = async () => { calls.signup++; await w.pdCompletePassengerRegistration(); };
  w.pdRegisterPassengerTelegram = async () => {
    if (!signed) { calls.launch++; return; }
    calls.telegram++;
    if (registered) await w.pdCompletePassengerRegistration();
  };
  // Deployed driver handler checks validity before sending any files.
  w.pdRegisterDriver = async () => {
    if (d.getElementById('pdObDriver').checkValidity()) calls.driver++;
  };
  w.eval(source);
  return {w, d, calls, close: () => dom.window.close()};
}
function input(s, id, value) {
  const el = s.d.getElementById(id); el.value = value;
  el.dispatchEvent(new s.w.Event('input', {bubbles: true})); return el;
}
function validPassenger(s) {
  input(s, 'pdObPassengerName', 'Тест Пассажир');
  input(s, 'pdObPassengerPhone', '+370 600-00000');
  s.d.getElementById('pdRegistrationConsent').checked = true;
}
(async () => {
  for (const lang of ['ru','en','lt']) {
    const s = setup({lang});
    input(s, 'pdObPassengerEmail', 'invalid');
    await s.w.pdRegisterPassengerTelegram();
    assert.equal(s.calls.launch, 1, 'Guest sign-in reaches Telegram launch without signup consent/email');
    assert.equal(s.calls.api.length, 0);
    s.close();
  }
  {
    const s = setup({signed: true, registered: true});
    input(s, 'pdObPassengerEmail', 'invalid');
    await s.w.pdRegisterPassengerTelegram();
    assert.equal(s.calls.telegram, 1);
    assert.equal(s.calls.completed, 1);
    assert.equal(s.calls.api.length, 0, 'Sign-in does not overwrite saved profile from the signup form');
    s.close();
  }
  {
    const s = setup({signed: true});
    await s.w.pdRegisterPassengerTelegram();
    assert.equal(s.calls.telegram, 0, 'New signup still requires explicit consent');
    s.d.getElementById('pdRegistrationConsent').checked = true;
    input(s, 'pdObPassengerEmail', 'user@localhost');
    await s.w.pdRegisterPassengerTelegram();
    assert.equal(s.calls.telegram, 0, 'Reject email that would fail server validation');
    input(s, 'pdObPassengerEmail', '');
    await s.w.pdRegisterPassengerTelegram();
    assert.equal(s.calls.telegram, 1);
    s.close();
  }
  for (const badPhone of ['abc', '123', '+370+60000000', '1234567890123456']) {
    const s = setup({signed: true}); validPassenger(s);
    const phone = input(s, 'pdObPassengerPhone', badPhone);
    await s.w.pdRegisterPassenger();
    assert.equal(s.calls.signup, 0, badPhone);
    assert.equal(phone.checkValidity(), false);
    input(s, 'pdObPassengerPhone', '+370 (600) 00000');
    await s.w.pdRegisterPassenger();
    assert.equal(s.calls.signup, 1, 'Correcting phone clears validation error');
    s.close();
  }
  for (const [id, value] of [['pdObPassengerName','   '], ['pdObPassengerName',' A '], ['pdObPassengerEmail','user@localhost']]) {
    const s = setup({signed: true}); validPassenger(s); input(s, id, value);
    await s.w.pdRegisterPassenger();
    assert.equal(s.calls.signup, 0, id);
    assert.equal(s.calls.api.length, 0, 'Invalid data never writes a passenger record'); s.close();
  }
  {
    const s = setup({signed: true}); validPassenger(s);
    input(s, 'pdObPassengerEmail', 'passenger@example.test');
    await s.w.pdRegisterPassenger();
    assert.equal(s.calls.completed, 1);
    const saved = s.calls.api.find(x => x.url === '/api/profile/details').body;
    assert.deepEqual(JSON.parse(JSON.stringify(saved)), {email: 'passenger@example.test', home_city: 'Vilnius', preferences: 'Quiet'});
    s.close();
  }
  {
    const s = setup({signed: true}); validPassenger(s);
    input(s, 'pdObPassengerEmail', 'passenger@example.test');
    s.w.api = async url => {if (url === '/api/profile/details') throw Error('offline'); return {profile: {}};};
    await assert.rejects(() => s.w.pdRegisterPassenger(), /Регистрация сохранена.*email/);
    assert.equal(s.calls.completed, 0); s.close();
  }
  {
    const s = setup({signed: true});
    input(s, 'pdObDriverName', 'Test Pilot'); input(s, 'pdObDriverPhone', 'abc');
    // Stage-one deployment hides and disables the vehicle fields.
    for(const id of ['pdObDriverCity','pdObDriverVehicle','pdObDriverYear','pdObDriverSeats','pdObDriverPlate']) s.d.getElementById(id).disabled = true;
    await s.w.pdRegisterDriver(); assert.equal(s.calls.driver, 0);
    input(s, 'pdObDriverPhone', '+37060000000');
    await s.w.pdRegisterDriver(); assert.equal(s.calls.driver, 1); s.close();
  }
  console.log('PASS registration: guest Telegram entry RU/EN/LT; existing-account entry; signup consent retained; name/phone/email validation and correction; existing profile preserved; optional email failure; pilot phone validation');
})().catch(e => {console.error(e); process.exitCode = 1;});
