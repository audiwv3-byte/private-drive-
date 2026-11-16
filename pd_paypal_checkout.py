"""PRIVATE DRIVE PayPal Orders v2 gateway.

Disabled by default. No secret is sent to the browser. All paid amounts and
ownership checks originate from the server-side, confirmed booking record.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

def settings():
    mode = os.environ.get('PD_PAYPAL_MODE', 'disabled').strip().lower()
    if mode not in ('sandbox', 'live'):
        return None
    client = os.environ.get('PAYPAL_CLIENT_ID', '').strip()
    secret = os.environ.get('PAYPAL_CLIENT_SECRET', '').strip()
    if not client or not secret:
        return None
    # Fail closed: live settlement requires independently verified webhooks,
    # refunds/reconciliation review, and a separate production deployment.
    # This staged version intentionally cannot activate live payments.
    if mode == 'live':
        return None
    return {'mode': mode, 'client_id': client, 'secret': secret,
            'base': 'https://api-m.paypal.com' if mode == 'live'
                    else 'https://api-m.sandbox.paypal.com'}

def money(value):
    try:
        d = Decimal(str(value).replace(',', '.'))
        if not d.is_finite() or d <= 0 or d > 100000 or d != d.quantize(Decimal('.01')):
            raise ValueError()
        return f'{d:.2f}'
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError('Стоимость заказа требует подтверждения') from None

def _request(url, method, body=None, headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {},
                                 data=body)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read(100000))
            if not isinstance(result, dict):
                raise RuntimeError('Invalid PayPal response')
            return result
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'PayPal HTTP {exc.code}') from None

def access_token(cfg):
    creds = base64.b64encode((cfg['client_id']+':'+cfg['secret']).encode()).decode()
    result = _request(cfg['base']+'/v1/oauth2/token', 'POST',
        urllib.parse.urlencode({'grant_type':'client_credentials'}).encode(),
        {'Authorization':'Basic '+creds,
         'Content-Type':'application/x-www-form-urlencoded'})
    token = result.get('access_token')
    if not isinstance(token, str) or not token:
        raise RuntimeError('PayPal token missing')
    return token

def call(cfg, method, path, payload=None, request_id=None):
    headers = {'Authorization':'Bearer '+access_token(cfg),
               'Content-Type':'application/json'}
    if request_id:
        headers['PayPal-Request-Id'] = request_id
    return _request(cfg['base']+path, method,
                    json.dumps(payload).encode() if payload is not None else None,
                    headers)

def create(cfg, booking_id, amount):
    if not isinstance(booking_id, int) or booking_id <= 0:
        raise ValueError('Invalid booking')
    amt = money(amount)
    response = call(cfg, 'POST', '/v2/checkout/orders',
        {'intent':'CAPTURE', 'purchase_units':[{
            'reference_id':str(booking_id),
            'description':f'PRIVATE DRIVE — заказ №{booking_id}',
            'custom_id':f'pd-{booking_id}',
            'amount':{'currency_code':'EUR', 'value':amt}}]},
        f'pd-create-{cfg["mode"]}-{booking_id}-{amt.replace(".","")}')
    if response.get('status') not in ('CREATED', 'PAYER_ACTION_REQUIRED', 'SAVED'):
        raise RuntimeError('PayPal order not ready')
    order_id = response.get('id')
    if not isinstance(order_id, str) or not re.fullmatch(r'[A-Z0-9]{12,32}',order_id):
        raise RuntimeError('Invalid PayPal order ID')
    return order_id

def capture(cfg, paypal_order_id, booking_id):
    if not re.fullmatch(r'[A-Z0-9]{12,32}',paypal_order_id):
        raise ValueError('Invalid PayPal order ID')
    result = call(cfg, 'POST',
        '/v2/checkout/orders/'+paypal_order_id+'/capture',
        request_id=f'pd-capture-{cfg["mode"]}-{booking_id}-{paypal_order_id}')
    return result

def validated_capture(result, booking_id, expected):
    """Reject completed orders with mismatched amount, currency or reference."""
    if result.get('status') != 'COMPLETED':
        raise ValueError('PayPal payment not completed')
    units = result.get('purchase_units')
    if not isinstance(units,list) or len(units)!=1:
        raise ValueError('Unexpected PayPal purchase units')
    unit = units[0]
    if unit.get('reference_id') != str(booking_id) or unit.get('custom_id') != f'pd-{booking_id}':
        raise ValueError('PayPal booking reference mismatch')
    payments = unit.get('payments') or {}
    captures = payments.get('captures')
    if not isinstance(captures,list) or len(captures)!=1:
        raise ValueError('PayPal capture not found')
    cap = captures[0]
    amount = cap.get('amount') or {}
    if (cap.get('status') != 'COMPLETED' or
        amount.get('currency_code') != 'EUR' or
        money(amount.get('value')) != money(expected)):
        raise ValueError('PayPal payment amount mismatch')
    capid=cap.get('id')
    if not isinstance(capid,str) or not re.fullmatch(r'[A-Z0-9]{12,32}',capid):
        raise ValueError('Invalid PayPal capture ID')
    return capid
