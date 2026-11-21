"""Read-only Twilio setup checks for private isolated-service startup logs.

No messages, verification requests or settings writes. Never return credentials,
account identifiers, friendly names, response bodies or authorization headers.
"""
import base64
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect_setup(env, *, open_url=None):
    summary = {
        'sms_live_flag': env.get('PD_NATIVE_SMS_LIVE') == 'YES',
        'verify_enabled_flag': env.get('TWILIO_VERIFY_ENABLED', '').lower() == 'true',
        'sms_sent': False,
    }
    if env.get('PD_NATIVE_SMS_ISOLATED') != 'YES':
        return {**summary, 'status': 'not_isolated'}
    required = ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_VERIFY_SERVICE_SID')
    missing = [key for key in required if not env.get(key)]
    if missing:
        return {**summary, 'status': 'missing_configuration', 'missing': missing}
    account = env['TWILIO_ACCOUNT_SID']
    service = env['TWILIO_VERIFY_SERVICE_SID']
    if not re.fullmatch(r'AC[0-9a-fA-F]{32}', account) or not re.fullmatch(r'VA[0-9a-fA-F]{32}', service):
        return {**summary, 'status': 'invalid_identifier_format'}
    open_url = open_url or build_opener(_NoRedirect()).open
    authorization = base64.b64encode((account + ':' + env['TWILIO_AUTH_TOKEN']).encode()).decode()

    def read(url):
        request = Request(url, method='GET', headers={
            'Authorization': 'Basic ' + authorization, 'Accept': 'application/json'})
        with open_url(request, timeout=5) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('oversized_response')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('invalid_response')
            return data

    try:
        data = read('https://api.twilio.com/2010-04-01/Accounts/' + account + '.json')
        summary['account_status'] = data.get('status') if data.get('status') in {'active', 'suspended', 'closed'} else 'unknown'
        summary['account_type'] = data.get('type') if data.get('type') in {'Trial', 'Full'} else 'unknown'
        data = read('https://api.twilio.com/2010-04-01/Accounts/' + account + '/Balance.json')
        balance = Decimal(str(data.get('balance')))
        if not balance.is_finite():
            raise ValueError('invalid_balance')
        summary['balance'] = str(balance)
        currency = data.get('currency')
        summary['currency'] = currency if isinstance(currency, str) and re.fullmatch(r'[A-Z]{3}', currency) else 'unknown'
        data = read('https://verify.twilio.com/v2/Services/' + service)
        summary['verify_service_accessible'] = True
        summary['service_matches_account'] = data.get('account_sid') == account
        length = data.get('code_length')
        summary['code_length'] = length if isinstance(length, int) and 4 <= length <= 10 else None
        summary['status'] = 'read_only_checks_completed'
    except HTTPError as error:
        summary['status'] = 'provider_http_' + str(error.code)
        error.close()
    except (OSError, ValueError, TypeError, InvalidOperation):
        summary['status'] = 'provider_unavailable_or_invalid_response'
    return summary
