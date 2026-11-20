import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {makeRegistrationClient} from './site_preview/registration-client.mjs';

test('passenger request and verify, no token exposure', async () => {
  const requests = [];
  const client = makeRegistrationClient(async (path, payload) => {
    requests.push({path, payload});
    if (path.endsWith('request-code')) return {status:202, body:{challenge_id:'local-challenge',expires_in:300}};
    return {status:200, body:{verified:true,role:'passenger',approval_status:'not_required',pilot_access:false,access_token:'never-expose'}};
  });
  assert.deepEqual(await client.requestCode({role:'passenger',channel:'email',destination:'person@example.test'}),{challengeRequested:true,expiresIn:300});
  const result = await client.verifyCode('123456');
  assert.deepEqual(result,{role:'passenger',approvalStatus:'not_required'});
  assert.equal(requests[0].path,'/test-registration/request-code');
  assert.equal(requests[1].path,'/test-registration/verify-code');
  assert.equal(requests[1].payload.role,undefined);
  assert.equal(JSON.stringify(result).includes('never-expose'),false);
  await assert.rejects(client.verifyCode('123456'),/no_active_challenge/);
});
test('pilot role is server-confirmed, pending, never granted access', async () => {
  const client = makeRegistrationClient(async path => path.endsWith('request-code')
    ? {status:202,body:{challenge_id:'c1'}}
    : {status:200,body:{verified:true,role:'pilot',approval_status:'pending',pilot_access:false}});
  await client.requestCode({role:'pilot',channel:'email',destination:'pilot@example.test'});
  assert.deepEqual(await client.verifyCode('123456'),{role:'pilot',approvalStatus:'pending'});
});
test('role forgery and pilot approval are rejected', async () => {
  const client = makeRegistrationClient(async path => path.endsWith('request-code')
    ? {status:202,body:{challenge_id:'c1'}}
    : {status:200,body:{verified:true,role:'passenger',approval_status:'not_required',pilot_access:true}});
  await client.requestCode({role:'pilot',channel:'email',destination:'pilot@example.test'});
  await assert.rejects(client.verifyCode('123456'),/verification_failed/);
});
test('bad input cannot reach transport', async () => {
  let calls=0;
  const client = makeRegistrationClient(async()=>{calls++;return null;});
  await assert.rejects(client.requestCode({role:'dispatcher',channel:'email',destination:'a@example.test'}),/invalid_role/);
  await assert.rejects(client.requestCode({role:'passenger',channel:'email',destination:''}),/invalid_destination/);
  await assert.rejects(client.verifyCode('abc'),/no_active_challenge/);
  assert.equal(calls,0);
});
test('public preview remains disabled and has no network transport', () => {
  const html=readFileSync('site_preview/registration.html','utf8');
  const client=readFileSync('site_preview/registration-client.mjs','utf8');
  assert.match(html, /const local = host === 'localhost'/);
  assert.match(html, /typeof transport === 'function'/);
  assert.match(html, /id="request-code"[^>]*disabled/);
  assert.match(html, /id="verify-code"[^>]*disabled/);
  assert.match(html, /id="otp"[^>]*disabled/);
  assert.doesNotMatch(client.replace(/\/\*[\s\S]*?\*\//g, ''), /\bfetch\s*\(|XMLHttpRequest|localStorage|sessionStorage|https?:\/\//);
});
