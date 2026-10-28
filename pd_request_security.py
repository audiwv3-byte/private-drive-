"""Strict Telegram identity parsing and bounded JSON requests for PRIVATE DRIVE."""
import hashlib
import hmac
import json
import re
import time
import urllib.parse


def verify_telegram_user(init_data, token, max_age=86400, now=None):
    """Validate the signed original initData; never trust initDataUnsafe."""
    if not init_data:
        raise PermissionError('Откройте приложение внутри Telegram')
    invalid = 'Данные входа повреждены. Откройте приложение заново в Telegram'
    try:
        if not isinstance(init_data, str) or len(init_data) > 16384:
            raise ValueError()
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True,
            strict_parsing=True, errors='strict', max_num_fields=32)
        params = dict(pairs)
        if len(params) != len(pairs) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) for key in params):
            raise ValueError()
        signature = params.get('hash', '')
        if not re.fullmatch(r'[0-9a-f]{64}', signature):
            raise ValueError()
        data = '\n'.join(key+'='+value for key, value in sorted(pairs) if key != 'hash')
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        raw_date = params.get('auth_date', '')
        if not re.fullmatch(r'[0-9]{1,12}', raw_date):
            raise ValueError()
        auth_date = int(raw_date)
        clock = time.time() if now is None else now
        if auth_date > clock+60 or clock-auth_date > max_age:
            raise PermissionError('Сессия устарела, откройте приложение заново')
        user = json.loads(params['user'])
        if not isinstance(user, dict) or type(user.get('id')) is not int or not 0 < user['id'] < 2**52:
            raise ValueError()
        return user['id'], user
    except (ValueError, TypeError, KeyError, OverflowError):
        raise PermissionError(invalid) from None


def register_request_guard(app):
    from flask import request, jsonify

    @app.before_request
    def pd_validate_json_object():
        if request.method not in ('POST', 'PUT', 'PATCH') or not request.path.startswith('/api/'):
            return
        # Payment provider signatures must cover the original webhook bytes.
        if request.path == '/api/stripe/webhook':
            return
        # Document uploads retain their existing file validation and limits.
        if request.path == '/api/driver/application' and request.mimetype == 'multipart/form-data':
            return
        if not request.is_json:
            return jsonify(error='Отправьте данные в формате JSON'), 415
        if request.content_length is not None and request.content_length > 65536:
            return jsonify(error='Слишком большой запрос. Сократите данные и повторите отправку'), 413
        if not isinstance(request.get_json(silent=True), dict):
            return jsonify(error='Некорректные данные запроса. Обновите приложение и повторите попытку'), 400
