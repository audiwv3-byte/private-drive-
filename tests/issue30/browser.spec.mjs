import { test, expect } from '@playwright/test';

const FIRST=['license_front','license_back','car_front','car_rear','car_interior'];
const SECOND=['registration_front','ltsa','activity','insurance','portrait'];
const ALL=[...FIRST,'registration_back',...SECOND];
const SHA_A='a'.repeat(64), SHA_B='b'.repeat(64);

async function launch(page, {
  stage=1, missing=[], rejectNext=false, denied=false,
}={}) {
  const state={
    documents:Object.fromEntries(ALL.map(side=>[side,{
      status: side==='registration_back' ? 'missing' : stage===2&&FIRST.includes(side) ? 'approved' : 'pending',
      sha256:SHA_A
    }])),
    decisions:[], applicationApproved:false, replaceCount:0, rejectedCount:0,
    rejectNext, denied, seenAuth:[], sawMultipart:false
  };
  for(const side of missing) state.documents[side]={status:'missing'};
  await page.route('**/api/**',async route=>{
    const request=route.request(), url=new URL(request.url()), path=url.pathname;
    const auth=request.headers()['x-telegram-init-data'];
    state.seenAuth.push(auth);
    if(auth!=='SYNTHETIC_BROWSER_TOKEN_DO_NOT_USE_IN_PRODUCTION') {
      return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:'Требуется авторизация'})});
    }
    const answer=(status,data)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    if(state.denied) return answer(403,{error:'Доступ запрещён'});
    if(path==='/api/admin/driver-applications/1001/document-reviews'&&request.method()==='GET') {
      return answer(200,{documents:state.documents});
    }
    const decision=path.match(/^\/api\/admin\/driver-applications\/1001\/document-reviews\/([a-z_]+)$/);
    if(decision&&request.method()==='POST') {
      const side=decision[1], body=request.postDataJSON();
      state.decisions.push({side,...body});
      if(state.rejectNext) {state.rejectNext=false;return answer(409,{error:'Документ обновлён. Открой его заново'});}
      if(!state.documents[side]?.sha256||body.sha256!==state.documents[side].sha256) {
        return answer(409,{error:'Неверный SHA-256'});
      }
      if(body.status==='rejected'&&String(body.reason||'').trim().length<3) return answer(400,{error:'Укажи причину отклонения'});
      if(body.status==='rejected') state.rejectedCount++;
      state.documents[side]={...state.documents[side],status:body.status};
      return answer(200,{ok:true,status:body.status});
    }
    const replacement=path.match(/^\/api\/admin\/driver-applications\/1001\/documents\/([a-z_]+)\/replace$/);
    if(replacement&&request.method()==='POST') {
      const side=replacement[1],body=request.postData()||'';
      state.sawMultipart=request.headers()['content-type']?.includes('multipart/form-data')&&body.includes('expected_sha256');
      if(!state.sawMultipart) return answer(400,{error:'Некорректная загрузка'});
      if(state.rejectNext) {state.rejectNext=false;return answer(409,{error:'Файл уже изменён'});}
      state.replaceCount++;
      state.documents[side]={status:'pending',sha256:SHA_B};
      return answer(200,{changed:true,status:'pending',sha256:SHA_B});
    }
    if(path==='/api/admin/driver-applications/1001/decision'&&request.method()==='POST') {
      state.applicationApproved=true;
      const required=stage===1?FIRST:[...FIRST,...SECOND];
      if(!required.every(side=>state.documents[side]?.status==='approved')) {
        return answer(409,{error:'Не все документы одобрены'});
      }
      return answer(200,{ok:true});
    }
    if(path.startsWith('/api/driver/documents/')) return route.fulfill({
      status:404,contentType:'application/json',body:JSON.stringify({error:'Синтетическая фотография отсутствует'})
    });
    return answer(404,{error:'Неизвестный синтетический маршрут'});
  });
  await page.goto('/tests/issue30/browser_fixture.html'+(stage===2?'?stage=2':''));
  await expect(page.getByRole('heading',{name:'Документы пилота — индивидуальная проверка'})).toBeVisible();
  await page.waitForFunction(()=>Boolean(window.pdIssue30Synthetic));
  return state;
}
const item=(page,label)=>page.locator('.pd-issue30-document').filter({hasText:label});

test('first stage: main approval is disabled until every required document approved',async({page})=>{
  const state=await launch(page);
  const primary=page.getByRole('button',{name:'Одобрить заявку'});
  await expect(primary).toBeDisabled();
  for(const [side,label] of [
    ['license_front','Права — лицевая сторона'],['license_back','Права — обратная сторона'],
    ['car_front','Авто — спереди'],['car_rear','Авто — сзади'],['car_interior','Авто — салон']
  ]) {
    await item(page,label).getByRole('button',{name:'Одобрить',exact:true}).click();
    await expect(item(page,label).getByText('approved')).toBeVisible();
    await page.evaluate(()=>window.pdIssue30Synthetic.loadOverview());
    if(side!=='car_interior') await expect(primary).toBeDisabled();
  }
  await expect(primary).toBeEnabled();
  await primary.click();
  expect(state.applicationApproved).toBeTruthy();
  expect(state.decisions).toHaveLength(5);
  expect(state.seenAuth.every(x=>x==='SYNTHETIC_BROWSER_TOKEN_DO_NOT_USE_IN_PRODUCTION')).toBeTruthy();
});

test('missing file cannot be approved or replaced',async({page})=>{
  await launch(page,{missing:['license_front']});
  const row=item(page,'Права — лицевая сторона');
  await expect(row.getByRole('button',{name:'Одобрить',exact:true})).toBeDisabled();
  await expect(row.getByRole('button',{name:'Заменить документ'})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Одобрить заявку'})).toBeDisabled();
});

test('rejected review and server 409 are visibly handled without silent approval',async({page})=>{
  const state=await launch(page);
  const row=item(page,'Права — лицевая сторона');
  await row.locator('input[placeholder="Причина отклонения"]').fill('Фото нечеткое');
  await row.getByRole('button',{name:'Отклонить'}).click();
  await expect(row.getByText('rejected')).toBeVisible();
  expect(state.rejectedCount).toBe(1);
  await expect(page.getByRole('button',{name:'Одобрить заявку'})).toBeDisabled();
  state.rejectNext=true;
  await row.getByRole('button',{name:'Одобрить',exact:true}).click();
  await expect(page.locator('#document-review-host [role=status]')).toContainText('Документ обновлён');
  await expect(row.getByRole('button',{name:'Одобрить',exact:true})).toBeEnabled();
  expect(state.documents.license_front.status).toBe('rejected');
});

test('replacement uploads synthetic image and resets prior approval',async({page})=>{
  const state=await launch(page);
  const row=item(page,'Права — лицевая сторона');
  await row.getByRole('button',{name:'Одобрить',exact:true}).click();
  await expect(row.getByText('approved')).toBeVisible();
  await row.locator('input[type=file]').setInputFiles({
    name:'synthetic.jpg',mimeType:'image/jpeg',buffer:Buffer.from([0xff,0xd8,0xff,0xd9])
  });
  await row.getByRole('button',{name:'Заменить документ'}).click();
  await expect(row.getByText('pending')).toBeVisible();
  expect(state.replaceCount).toBe(1);
  expect(state.sawMultipart).toBeTruthy();
  expect(state.documents.license_front.sha256).toBe(SHA_B);
});

test('stage2 optional registration back does not block and first-stage reviews still required',async({page})=>{
  await launch(page,{stage:2});
  const primary=page.getByRole('button',{name:'Одобрить заявку'});
  await expect(primary).toBeDisabled();
  await expect(item(page,'Техпаспорт — обратная сторона').getByRole('button',{name:'Одобрить',exact:true})).toBeDisabled();
  for(const label of ['Техпаспорт — лицевая сторона','LTSA','Индивидуальная деятельность','Страховка','Фото пилота']){
    await item(page,label).getByRole('button',{name:'Одобрить',exact:true}).click();
  }
  await page.evaluate(()=>window.pdIssue30Synthetic.loadOverview());
  await expect(primary).toBeEnabled();
});

test('API access denied gives visible error and keeps gate closed',async({page})=>{
  await launch(page,{denied:true});
  await expect(page.locator('#document-review-host [role=status]')).toContainText('Доступ запрещён');
  await expect(page.getByRole('button',{name:'Одобрить заявку'})).toBeDisabled();
});

for(const width of [390,320]){
  test('mobile '+width+'px: documents fit viewport and controls usable',async({page})=>{
    await page.setViewportSize({width,height:844});
    await launch(page);
    await expect(item(page,'Права — лицевая сторона').getByRole('button',{name:'Одобрить',exact:true})).toBeVisible();
    const sizes=await page.evaluate(()=>({
      scroll:document.documentElement.scrollWidth,
      viewport:document.documentElement.clientWidth,
      buttons:[...document.querySelectorAll('.pd-issue30-document button')].map(el=>el.getBoundingClientRect().height)
    }));
    expect(sizes.scroll).toBeLessThanOrEqual(sizes.viewport+1);
    expect(Math.min(...sizes.buttons)).toBeGreaterThanOrEqual(40);
    await item(page,'Права — лицевая сторона').getByRole('button',{name:'Одобрить',exact:true}).click();
    await expect(item(page,'Права — лицевая сторона').getByText('approved')).toBeVisible();
  });
}
