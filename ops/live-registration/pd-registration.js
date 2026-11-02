/* Live form enhancement: retains the deployed Telegram auth and role handlers. */
(()=>{
'use strict';
const form=document.getElementById('pdObPassenger'),header=document.querySelector('.pd-branded-header');
if(!form||!header||window.pdRegistrationV1)return;window.pdRegistrationV1=true;
const t=(ru,en,lt)=>window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru;
const logo=header.querySelector('.pd-official-logo');if(logo)logo.src='/assets/private-drive-logo-transparent-v1.png';
const brand=header.querySelector('.pd-brand-wordmark');
if(brand){brand.querySelector('strong').textContent='PRIVATE DRIVE';brand.querySelector('span').textContent='VILNIUS • LIETUVA • EUROPA'}
const language=document.createElement('select');language.id='pdRegistrationLanguage';language.setAttribute('aria-label',t('Язык','Language','Kalba'));
for(const value of ['ru','en','lt']){const o=document.createElement('option');o.value=value;o.textContent=value.toUpperCase();language.append(o)}
language.value=window.PD_LANG||'ru';language.onchange=()=>{try{localStorage.setItem('pdOnboardingLanguage',language.value)}catch(_){}pdSwitchLanguage(language.value)};header.append(language);
// The original shared hero remains the live-home anchor; its picture is now the page background.
const privacy=document.querySelector('.pd-privacy-bar');
const shared=document.getElementById('pdSharedHero'),pilotBack=document.getElementById('pdPilotBack');
if(shared&&privacy)shared.append(privacy);
if(shared&&pilotBack)shared.after(pilotBack);
form.querySelector('h1').textContent=t('Регистрация','Registration','Registracija');
const name=document.getElementById('pdObPassengerName'),phone=document.getElementById('pdObPassengerPhone');
name.placeholder=t('Имя','Name','Vardas');phone.placeholder='+370…';
const emailLabel=document.createElement('label');emailLabel.htmlFor='pdObPassengerEmail';emailLabel.textContent=t('Электронная почта · необязательно','Email · optional','El. paštas · neprivaloma');
const email=document.createElement('input');email.id=emailLabel.htmlFor;email.type='email';email.autocomplete='email';email.maxLength=254;email.placeholder=t('Электронная почта','Email','El. paštas');
phone.after(emailLabel,email);
// Match server validation before registration writes the passenger record.
function validateName(input){
 const value=input.value.trim().replace(/\s+/g,' ');
 input.setCustomValidity(value.length>=2&&value.length<=80?'':t('Укажите имя: от 2 до 80 символов','Enter a name: 2 to 80 characters','Įveskite vardą: nuo 2 iki 80 simbolių'));
}
function validatePhone(input){
 const value=input.value.trim(),digits=value.replace(/\D/g,'');
 input.setCustomValidity(/^\+?[0-9\s().-]+$/.test(value)&&digits.length>=7&&digits.length<=15?'':t('Укажите корректный номер телефона','Enter a valid phone number','Įveskite teisingą telefono numerį'));
}
function validateEmail(){
 const value=email.value.trim();
 email.setCustomValidity(!value||/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)?'':t('Проверьте электронную почту','Check the email address','Patikrinkite el. pašto adresą'));
}
for(const [id,validate] of [['pdObPassengerName',validateName],['pdObPassengerPhone',validatePhone],['pdObDriverName',validateName],['pdObDriverPhone',validatePhone]]){
 const input=document.getElementById(id);if(input)input.addEventListener('input',()=>validate(input));
}
email.addEventListener('input',validateEmail);
const consent=document.createElement('label');consent.className='pd-registration-consent';
const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.required=true;checkbox.id='pdRegistrationConsent';
const consentText=document.createElement('span');consentText.append(t('Принимаю ','I accept the ','Sutinku su '));
function link(path,text){const a=document.createElement('a');a.href=path+'?lang='+(window.PD_LANG||'ru');a.target='_blank';a.rel='noopener noreferrer';a.textContent=text;return a}
consentText.append(link('/legal',t('условия','terms','sąlygomis')),t(' и ',' and ',' ir '),link('/privacy',t('политику конфиденциальности','privacy policy','privatumo politika')));consent.append(checkbox,consentText);
const actions=form.querySelector('.actions');actions.before(consent);
// Keep the original paragraphs available to screen readers without duplicating the card footer.
for(const p of form.querySelectorAll(':scope > p'))p.classList.add('hidden');
const back=actions.querySelector('button[type="button"]');if(back){back.textContent=t('Для пилотов · регистрация водителя','For pilots · driver registration','Pilotams · vairuotojo registracija');back.classList.add('pd-registration-role');back.onclick=()=>pdShowOnboarding('driver')}
const telegram=form.querySelector('[onclick="pdRegisterPassengerTelegram()"]');if(telegram){telegram.classList.add('pd-registration-login');telegram.textContent=t('Уже есть аккаунт? Войти через Telegram','Have an account? Sign in with Telegram','Turite paskyrą? Prisijunkite per Telegram')}
const footer=document.createElement('div');footer.className='pd-registration-footer';footer.append(link('/legal',t('Условия поездки и оплаты','Trip and payment terms','Kelionės ir mokėjimo sąlygos')),link('/privacy',t('Политика конфиденциальности','Privacy policy','Privatumo politika')));const contact=document.createElement('a');contact.href='mailto:eurobaltictransfer@gmail.com';contact.textContent=t('Связаться с нами','Contact us','Susisiekite');const support=document.createElement('a');support.href='https://t.me/PrivatDraiv';support.textContent='Telegram';support.target='_blank';support.rel='noopener noreferrer';footer.append(contact,support);form.append(footer);
// Existing users/driver/admin routing is still decided by the original handler.
const show=pdShowOnboarding;pdShowOnboarding=function(stage){const u=window.pdOnboardingUser;const guest=!u?.registered&&!u?.admin&&!u?.pilot_access;return show(guest&&(stage==='role'||stage==='language')?'passenger':stage)};
const complete=pdCompletePassengerRegistration;
pdCompletePassengerRegistration=async function(){
 const value=email.value.trim();
 // Signing in must not overwrite an existing profile with registration-form text.
 if(value&&!window.pdOnboardingUser?.registered){
  const me=await api('/api/me'),profile=me.profile||{};
  try{await api('/api/profile/details',{email:value,home_city:profile.home_city||'',preferences:profile.preferences||''})}
  catch(e){throw new Error(t('Регистрация сохранена, но email не удалось сохранить. Повторите попытку: ','Registration saved, but the email could not be saved. Please retry: ','Registracija išsaugota, bet el. pašto išsaugoti nepavyko. Bandykite dar kartą: ')+e.message)}
 }
 return complete();
};
const register=pdRegisterPassenger;pdRegisterPassenger=async function(){validateName(name);validatePhone(phone);validateEmail();if(!form.reportValidity())return;return register()};
const registerTelegram=pdRegisterPassengerTelegram;pdRegisterPassengerTelegram=async function(){
 // Outside Telegram the original handler shows the launch link. It must run
 // before signup consent checks: the visitor may already have an account.
 if(typeof initData==='undefined'||!initData||window.pdOnboardingUser?.registered)return registerTelegram();
 if(!checkbox.checked){checkbox.reportValidity();return}
 validateEmail();if(!email.reportValidity())return;return registerTelegram();
};
const registerDriver=pdRegisterDriver;pdRegisterDriver=async function(){
 const driverName=document.getElementById('pdObDriverName'),driverPhone=document.getElementById('pdObDriverPhone');
 if(driverName)validateName(driverName);if(driverPhone)validatePhone(driverPhone);
 return registerDriver();
};
// Apply to an already rendered welcome/language screen without disrupting signed-in roles.
if(!form.classList.contains('hidden')||['pdObRole','pdObLanguage'].some(id=>!document.getElementById(id)?.classList.contains('hidden')))pdShowOnboarding('passenger');
})();
