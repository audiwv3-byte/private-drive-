"""Explicit real-provider test, restricted to test credentials and 1 EUR test objects."""
import os,sys
import Euro_Baltic_Transfer  # loads the existing project .env; never prints its contents
import stripe
from pd_prepayment_v3 import plain
key=os.getenv('STRIPE_SECRET_KEY','').strip()
if not key.startswith('sk_test_'):raise SystemExit('STOP: sandbox check requires a test key')
stripe.api_key=key
stripe.max_network_retries=1
try:
    session=plain(stripe.checkout.Session.create(mode='payment',payment_method_types=['card'],customer_creation='always',
       line_items=[{'price_data':{'currency':'eur','unit_amount':100,'product_data':{'name':'PRIVATE DRIVE integration TEST ONLY'}},'quantity':1}],
       success_url='https://wilsonpark.pythonanywhere.com/?payment=test_return',cancel_url='https://wilsonpark.pythonanywhere.com/?payment=test_cancel',
       metadata={'pd_test':'integration-v3'},idempotency_key='pd-sandbox-checkout-20261027-v3'))
    assert session['livemode'] is False
    print('SANDBOX_CHECKOUT_OK')
    current=plain(stripe.checkout.Session.retrieve(session['id']))
    if current.get('status')=='open':stripe.checkout.Session.expire(session['id'])
    intent=plain(stripe.PaymentIntent.create(amount=100,currency='eur',payment_method_types=['card'],payment_method='pm_card_visa',confirm=True,
       metadata={'pd_test':'integration-v3'},idempotency_key='pd-sandbox-intent-20261027-v3'))
    assert intent['livemode'] is False and intent['status']=='succeeded' and intent['amount_received']==100
    print('SANDBOX_PAYMENT_OK')
    refund=plain(stripe.Refund.create(payment_intent=intent['id'],amount=100,idempotency_key='pd-sandbox-refund-20261027-v3'))
    assert refund.get('livemode',False) is False and refund['amount']==100
    print('SANDBOX_REFUND',refund['status'])
except Exception as exc:
    print('SANDBOX_CHECK_FAILED',type(exc).__name__)
    sys.exit(1)
