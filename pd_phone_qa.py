"""Single-worker, disposable passenger login for a dedicated QA web service."""
import hashlib
import hmac
import os
import secrets
import threading
import time

from flask import Flask, jsonify, request

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2048
phone = '+12025550101'
code_hash = os.environ['PD_QA_CODE_SHA256']
if len(bytes.fromhex(code_hash)) != 32:
    raise ValueError('Expected a SHA-256 digest')
lock = threading.Lock()
challenge = None
token = None
expires = 0
attempts = 0
used = False


@app.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/health')
def health():
    return jsonify(status='ok', sms_enabled=False)


@app.post('/native-auth/request-code')
def request_code():
    global challenge, expires
    if request.get_json(silent=True) != {'channel': 'phone', 'destination': phone}:
        return jsonify(error='sms_number_not_enabled'), 403
    with lock:
        if used or attempts >= 5:
            return jsonify(error='test_session_closed'), 403
        if challenge is None or time.monotonic() >= expires:
            challenge = secrets.token_urlsafe(32)
            expires = time.monotonic() + 300
        return jsonify(challenge_id=challenge, expires_in=int(expires-time.monotonic()), resend_after=30), 202


@app.post('/native-auth/verify-code')
def verify():
    global used, attempts, token, expires
    data = request.get_json(silent=True)
    with lock:
        if not isinstance(data, dict) or used or attempts >= 5 or not challenge or data.get('challenge_id') != challenge or time.monotonic() >= expires:
            return jsonify(error='invalid_or_expired_code'), 401
        attempts += 1
        code = data.get('code')
        if not isinstance(code, str) or not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), code_hash):
            return jsonify(error='invalid_or_expired_code'), 401
        used = True
        token = secrets.token_urlsafe(32)
        expires = time.monotonic() + 3600
        return jsonify(verified=True, role='passenger', user_id='qa-phone-passenger', access_token=token, token_type='Bearer', expires_in=3600)


@app.post('/native-auth/session')
@app.post('/native-auth/sign-out')
def session():
    global token
    with lock:
        if not token or time.monotonic() >= expires or not hmac.compare_digest(request.headers.get('Authorization','').encode(), ('Bearer '+token).encode()):
            return jsonify(error='unauthorized'), 401
        if request.path.endswith('/sign-out'):
            token = None
            return jsonify(ok=True)
        return jsonify(verified=True, role='passenger', user_id='qa-phone-passenger', expires_in=int(expires-time.monotonic()))
