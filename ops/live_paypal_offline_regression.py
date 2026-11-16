"""Offline tests of the actual PayPal production module, GET source only.
No PayPal external API requests, credentials, orders, DB or real payments.
"""
import hashlib,importlib.util,os,pathlib,re,tempfile,urllib.request
from unittest.mock import patch
URL="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_paypal_checkout.py"
def done(x):print("PASS",x,flush=True)
def expect_raises(fn):
    try:fn()
    except ValueError:return
    raise AssertionError("INVALID_INPUT_ACCEPTED")
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    req=urllib.request.Request(URL,method="GET",headers={"Authorization":"Token "+token})
    with urllib.request.urlopen(req,timeout=35) as r:
        source=r.read(200000)
    print("SOURCE_SHA256",hashlib.sha256(source).hexdigest(),flush=True)
    # Completely replace network call and use fake, non-sensitive credentials.
    with tempfile.TemporaryDirectory(prefix="pd-paypal-offline-") as td:
        path=pathlib.Path(td)/"pd_paypal_checkout.py";path.write_bytes(source)
        spec=importlib.util.spec_from_file_location("offline_live_paypal",path)
        pay=importlib.util.module_from_spec(spec);spec.loader.exec_module(pay)
        def no_network(*args,**kwargs):raise AssertionError("UNEXPECTED_EXTERNAL_PAYPAL_REQUEST")
        with patch.object(pay,"_request",side_effect=no_network):
            with patch.dict(os.environ,{"PD_PAYPAL_MODE":"disabled","PAYPAL_CLIENT_ID":"FAKE","PAYPAL_CLIENT_SECRET":"FAKE"},clear=True):
                assert pay.settings() is None
            done("DISABLED_DEFAULT_NO_PAYMENT")
            with patch.dict(os.environ,{"PD_PAYPAL_MODE":"live","PAYPAL_CLIENT_ID":"FAKE","PAYPAL_CLIENT_SECRET":"FAKE"},clear=True):
                assert pay.settings() is None
            done("LIVE_MODE_BLOCKED")
            with patch.dict(os.environ,{"PD_PAYPAL_MODE":"sandbox","PAYPAL_CLIENT_ID":"FAKE","PAYPAL_CLIENT_SECRET":"FAKE"},clear=True):
                cfg=pay.settings()
                assert cfg and cfg["base"]=="https://api-m.sandbox.paypal.com"
            done("SANDBOX_BASE_CONFIGURED")
            with patch.dict(os.environ,{"PD_PAYPAL_MODE":"sandbox","PAYPAL_CLIENT_ID":"","PAYPAL_CLIENT_SECRET":""},clear=True):
                assert pay.settings() is None
            done("MISSING_CREDENTIALS_FAIL_CLOSED")
            assert pay.money("15,25")=="15.25"
            for val in (None,"0","-5","NaN","Infinity","1.999","100000.01"):
                expect_raises(lambda val=val:pay.money(val))
            done("INVALID_AMOUNTS_REJECTED")
            def captured(amount="15.25",currency="EUR",booking=42,custom="pd-42",status="COMPLETED"):
                return {"status":status,"purchase_units":[{"reference_id":str(booking),"custom_id":custom,
                   "payments":{"captures":[{"id":"8AB1234567890123","status":"COMPLETED",
                            "amount":{"value":amount,"currency_code":currency}}]}}]}
            assert pay.validated_capture(captured(),42,"15.25")=="8AB1234567890123"
            for payload in (captured(amount="15.24"),captured(currency="USD"),
                            captured(booking=99),captured(custom="pd-99"),captured(status="PENDING")):
                expect_raises(lambda payload=payload:pay.validated_capture(payload,42,"15.25"))
            done("CAPTURE_AMOUNT_CURRENCY_BOOKING_CHECKED")
            expect_raises(lambda:pay.create({"mode":"sandbox"},42,"0"))
            done("INVALID_CREATE_NO_EXTERNAL_NETWORK")
    print("ALL_OFFLINE_LIVE_PAYPAL_CHECKS_PASSED",flush=True)
    print("NO_CREDENTIALS_READ_FROM_SERVER_NO_PROVIDER_TRAFFIC_NO_PAYMENT",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("OFFLINE_PAYPAL_TEST_FAILED",type(e).__name__,str(e)[:85],flush=True)
        raise SystemExit(1)
