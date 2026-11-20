/* Browser-only offline registration checks. No HTTP listener is started.
   Playwright fulfills two loopback URLs from checked-in files. The injected
   transport is fake, never contacts a server, and holds no real user data. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'site_preview');
const OUTPUT=path.join(ROOT,'registration-screenshots');
fs.mkdirSync(OUTPUT,{recursive:true});
const results=[];
const html=fs.readFileSync(path.join(ROOT,'registration.html'),'utf8');
const moduleJs=fs.readFileSync(path.join(ROOT,'registration-client.mjs'),'utf8');
const loopback='http://127.0.0.1:49999';
const external='https://example.test';
const widths=[{name:'iphone-small',width:320,height:740},{name:'iphone',width:390,height:844}];
async function serve(page,base) {
  await page.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.origin!==base) return route.abort('blockedbyclient');
    if(u.pathname==='/registration.html') return route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:html});
    if(u.pathname==='/registration-client.mjs') return route.fulfill({status:200,contentType:'application/javascript; charset=utf-8',body:moduleJs});
    return route.abort('blockedbyclient');
  });
}
async function capture(page,name) {
  const metrics=await page.evaluate(()=>({
    scrollWidth:document.documentElement.scrollWidth,
    clientWidth:document.documentElement.clientWidth,
    roleChecked:document.querySelector('input[name=role]:checked')?.value,
    requestDisabled:document.querySelector('#request-code').disabled,
    verifyDisabled:document.querySelector('#verify-code').disabled,
    otpVisible:!document.querySelector('#otp-step').hidden,
    status:document.querySelector('#registration-status').textContent,
  }));
  assert.ok(metrics.scrollWidth<=metrics.clientWidth,'horizontal overflow in '+name);
  await page.screenshot({path:path.join(OUTPUT,name+'.png'),fullPage:true});
  results.push({name,...metrics});
}
function localTransportFixture() {
  window.__PD_LOCAL_TEST_TRANSPORT__=async (endpoint,data)=>{
    window.__pdCalls ||= [];
    window.__pdCalls.push({endpoint,role:data.role||null});
    if(endpoint==='/test-registration/request-code') {
      window.__pdRole=data.role;
      return {status:202,body:{challenge_id:'offline-test-challenge',expires_in:300}};
    }
    if(endpoint==='/test-registration/verify-code') {
      if(data.code!=='123456') return {status:401,body:{error:'invalid_or_expired_code'}};
      return {status:200,body:{
        verified:true,role:window.__pdRole,approval_status:window.__pdRole==='pilot'?'pending':'not_required',
        pilot_access:false,access_token:'never_store_this_mock_token'
      }};
    }
    throw Error('Unexpected endpoint');
  };
}
async function run(){
  const browser=await chromium.launch({headless:true});
  try{
    for(const size of widths){
      const ctx=await browser.newContext({viewport:{width:size.width,height:size.height},deviceScaleFactor:1, isMobile:true,hasTouch:true});
      await ctx.addInitScript(localTransportFixture);
      const page=await ctx.newPage();
      const errors=[];
      page.on('pageerror',err=>errors.push(String(err)));
      await serve(page,loopback);
      await page.goto(loopback+'/registration.html',{waitUntil:'load'});
      await page.waitForFunction(()=>!document.querySelector('#request-code').disabled);
      assert.equal(await page.locator('#fullname').isEnabled(),true);
      assert.equal(await page.locator('#verify-code').isDisabled(),true);
      await capture(page,size.name+'-initial');

      // Validation: missing name/email/consent, invalid email must not call transport.
      await page.locator('#request-code').click();
      await assertStatus(page,'Заполни имя');
      await page.locator('#fullname').fill('Test Passenger');
      await page.locator('#email').fill('not-an-email');
      await page.locator('input[type=checkbox]').check();
      await page.locator('#request-code').click();
      await assertStatus(page,'Заполни имя');
      assert.equal(await page.evaluate(()=>window.__pdCalls?.length||0),0);

      await page.locator('#email').fill('passenger@example.test');
      await page.locator('#request-code').click();
      await page.waitForFunction(()=>!document.querySelector('#otp-step').hidden);
      await assertStatus(page,'Код создан локально');
      assert.equal(await page.locator('#verify-code').isEnabled(),true);
      assert.equal(await page.evaluate(()=>window.__pdCalls.length),1);
      await capture(page,size.name+'-passenger-otp');

      await page.locator('#otp').fill('000000');
      await page.locator('#verify-code').click();
      await assertStatus(page,'Неверный или истёкший');
      assert.equal(await page.locator('#verify-code').isEnabled(),true);
      await capture(page,size.name+'-otp-error');

      await page.locator('#otp').fill('123456');
      await page.locator('#verify-code').click();
      await assertStatus(page,'Пассажир проверен');
      assert.equal(await page.locator('#verify-code').isDisabled(),true);
      assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
      await capture(page,size.name+'-passenger-complete');
      assert.deepEqual(errors,[]);
      await ctx.close();

      // Independent pilot flow, never auto-approved.
      const pc=await browser.newContext({viewport:{width:size.width,height:size.height},deviceScaleFactor:1,isMobile:true,hasTouch:true});
      await pc.addInitScript(localTransportFixture);
      const pilot=await pc.newPage();
      await serve(pilot,loopback);
      await pilot.goto(loopback+'/registration.html');
      await pilot.waitForFunction(()=>!document.querySelector('#request-code').disabled);
      await pilot.locator('input[value=pilot]').check();
      await pilot.locator('#fullname').fill('Test Pilot');
      await pilot.locator('#email').fill('pilot@example.test');
      await pilot.locator('input[type=checkbox]').check();
      await pilot.locator('#request-code').click();
      await pilot.waitForFunction(()=>!document.querySelector('#otp-step').hidden);
      await pilot.locator('#otp').fill('123456');
      await pilot.locator('#verify-code').click();
      await assertStatus(pilot,'Пилот ожидает одобрения');
      assert.equal(await pilot.evaluate(()=>window.__pdRole),'pilot');
      await capture(pilot,size.name+'-pilot-pending');
      await pc.close();
    }
    // Static/public deployment must remain disabled even if an attacker injects transport.
    const ctx=await browser.newContext({viewport:{width:390,height:844}});
    await ctx.addInitScript(localTransportFixture);
    const page=await ctx.newPage();
    await serve(page,external);
    await page.goto(external+'/registration.html');
    await page.waitForLoadState('load');
    assert.equal(await page.locator('#request-code').isDisabled(),true);
    assert.equal(await page.locator('#fullname').isDisabled(),true);
    await capture(page,'public-disabled');
    await ctx.close();
  } finally {await browser.close();}
  fs.writeFileSync(path.join(OUTPUT,'audit.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results,null,2));
}
async function assertStatus(page,text){
  await page.waitForFunction(needle=>document.querySelector('#registration-status').textContent.includes(needle),text);
}
run().catch(e=>{console.error(e);process.exitCode=1});
