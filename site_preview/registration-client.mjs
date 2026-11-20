/**
 * PRIVATE DRIVE website-preview registration client.
 * Test-only. No fetch, XMLHttpRequest, storage, or production server URL.
 * The caller must explicitly inject a local-only WSGI test transport.
 */
export function makeRegistrationClient(transport) {
  if (typeof transport !== 'function') throw new TypeError('An explicit test transport is required');
  let challenge = null;
  let expectedRole = null;
  let verified = false;

  async function requestCode({role, channel, destination}) {
    if (!['passenger', 'pilot'].includes(role)) throw new Error('invalid_role');
    if (!['email', 'phone'].includes(channel)) throw new Error('invalid_channel');
    if (typeof destination !== 'string' || !destination.trim()) throw new Error('invalid_destination');
    challenge = null;
    verified = false;
    expectedRole = null;
    const res = await transport('/test-registration/request-code', {
      role, channel, destination: destination.trim()
    });
    if (!res || res.status !== 202 || typeof res.body?.challenge_id !== 'string') {
      throw new Error('request_failed');
    }
    challenge = res.body.challenge_id;
    expectedRole = role;
    return {challengeRequested: true, expiresIn: res.body.expires_in};
  }

  async function verifyCode(code) {
    if (!challenge || verified) throw new Error('no_active_challenge');
    if (typeof code !== 'string' || !/^\d{6}$/.test(code)) throw new Error('invalid_code_format');
    const res = await transport('/test-registration/verify-code', {
      challenge_id: challenge, code
    });
    if (!res || res.status !== 200 || res.body?.role !== expectedRole ||
        res.body?.verified !== true || res.body?.pilot_access !== false ||
        (expectedRole === 'pilot' && res.body?.approval_status !== 'pending')) {
      throw new Error('verification_failed');
    }
    verified = true;
    challenge = null;
    const result = {role: expectedRole, approvalStatus: res.body.approval_status};
    expectedRole = null;
    // Never expose/store access_token in a public website preview.
    return result;
  }

  return {requestCode, verifyCode};
}
