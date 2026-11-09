'use strict';
// Offline regression checks: no Telegram requests, orders, payments or production writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('miniapp/templates/index.html', 'utf8');
const language = html.match(/<div id="pdObLanguage"[\s\S]*?<\/div><p class="muted">PRIVATE DRIVE · Литва и Европа<\/p><\/div>/)?.[0];
assert.ok(language, 'Branded language-first screen is missing');
assert.match(language, /private-drive-official-logo\.jpeg/);
for (const [locale,flag,caption] of [['en','🇬🇧','English'],['lt','🇱🇹','Lietuvių'],['ru','🇷🇺','Русский']]) {
  assert.ok(language.includes('lang="'+locale+'"'), locale+' button missing');
  assert.ok(language.includes(flag) && language.includes(caption), locale+' flag or caption missing');
}
const start = html.slice(html.indexOf('function pdOnboardingStart(user){'),html.indexOf('async function pdCompletePassengerRegistration()'));
assert.ok(start.indexOf("if(!chosen){pdShowOnboarding('language');return}") > -1);
assert.ok(start.indexOf("if(!chosen){pdShowOnboarding('language');return}") < start.indexOf("if(user?.admin)"), 'Language selection is skipped for returning staff on a fresh device');
assert.ok(start.includes("if(user?.registered&&user.name&&user.phone){pdHideOnboarding();return}"), 'Do not re-register existing passengers');
const passenger = html.slice(html.indexOf('<form id="pdObPassenger"'),html.indexOf('<form id="pdObDriver"'));
assert.ok(passenger.indexOf('pdRegisterPassengerTelegram()') < passenger.indexOf('<details id="pdObManual"'), 'Telegram must be primary');
assert.ok(passenger.includes('pdRegisterPassenger()') && passenger.includes('Зарегистрироваться вручную'), 'Manual fallback must remain available');
assert.ok(html.includes("if(lang===window.PD_LANG)pdOnboardingStart(window.pdOnboardingUser);else pdSwitchLanguage(lang)"), 'Language choice must resume existing user role');
assert.ok(html.includes("document.body.dataset.pdOnboardingStage=stage"), 'Language splash style not activated');
assert.ok(html.includes("delete document.body.dataset.pdOnboardingStage"), 'Language splash style must clear');
assert.ok(html.includes("$('pdObManual').open=true"), 'Manual fallback must open when Telegram registration needs it');
console.log('PASS branded first-launch language selection for three languages');
console.log('PASS returning roles, Telegram-first registration and optional manual fallback');
