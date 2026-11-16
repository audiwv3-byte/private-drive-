"""Synthetic web-auth -> booking -> private payment-status API regression.
Uses disposable SQLite, fake OTP notifier, no real orders or provider calls.
"""
import importlib.util,pathlib,secrets,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]/"experimental"
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
identity=load("pd_web_identity_staged")
bookings=load("pd_web_bookings_staged")
ORIGIN="https://wilsonpark.pythonanywhere.com"
def ok(cond,name):
    if not cond:raise AssertionError(name)
    print("PASS",name,flush=True)
with tempfile.TemporaryDirectory(prefix="pd-web-booking-stage-") as td:
    d=str(pathlib.Path(td)/"testing.sqlite")
    delivered=[]
    app=identity.create_isolated_app(d,"synthetic-key-"+("a"*48),lambda e,c:delivered.append((e,c)),allowed_origin=ORIGIN)
    bookings.add_staged_web_bookings(app,d,origin=ORIGIN)
    def login(email):
        c=app.test_client()
        token=c.get("/api/web/csrf").json["csrf_token"]
        headers={"Origin":ORIGIN,"X-CSRF-Token":token}
        assert c.post("/api/web/start",headers=headers,json={"email":email}).status_code==200
        code=delivered[-1][1]
        assert c.post("/api/web/verify",headers=headers,json={"code":code}).status_code==200
        token=c.get("/api/web/csrf").json["csrf_token"]
        return c,token
    def submit(c,t,method="Банковский перевод",key=None,from_="Вильнюс",to="Каунас"):
        payload={"origin":from_,"destination":to,"payment_method":method,
                 "request_key":key or ("synthetic_"+secrets.token_hex(12))}
        return c.post("/api/web/bookings",headers={"Origin":ORIGIN,"X-CSRF-Token":t},json=payload)
    a,ta=login("web-one@example.test")
    b,tb=login("web-two@example.test")
    anon=app.test_client()
    ok(anon.get("/api/web/bookings").status_code==401,"ANONYMOUS_BOOKINGS_DENIED")
    ok(anon.post("/api/web/bookings",json={}).status_code==401,"ANONYMOUS_CREATE_DENIED")
    ca=submit(a,ta);cb=submit(b,tb)
    ok(ca.status_code==201 and cb.status_code==201,"TWO_SYNTHETIC_WEB_USERS_CREATE_OWN_BOOKINGS")
    id_a=ca.json["id"];id_b=cb.json["id"]
    ok(id_a!=id_b,"BOOKING_IDENTIFIERS_DISTINCT")
    one=a.get("/api/web/bookings").json["orders"]
    two=b.get("/api/web/bookings").json["orders"]
    ok(len(one)==1 and one[0]["id"]==id_a and len(two)==1 and two[0]["id"]==id_b,
       "WEB_BOOKING_LIST_OWNERSHIP")
    ok(a.get(f"/api/web/bookings/{id_b}/payment").status_code==404,
       "FOREIGN_WEB_PAYMENT_STATUS_HIDDEN")
    ok(b.get(f"/api/web/bookings/{id_a}/payment").status_code==404,
       "OTHER_WEB_PAYMENT_STATUS_HIDDEN")
    own=a.get(f"/api/web/bookings/{id_a}/payment")
    ok(own.status_code==200 and own.json["checkout_enabled"] is False,
       "STAGED_CHECKOUT_DISABLED")
    ok(submit(a,ta,"Наличными").status_code==400,"WEB_CASH_NEW_BOOKING_DENIED")
    ok(submit(a,ta,"Банковская карта").status_code==400,"UNCONFIGURED_STRIPE_CANNOT_ACTIVATE")
    ok(submit(a,ta,"PayPal").status_code==400,"PAYPAL_UNVERIFIED_CANNOT_ACTIVATE")
    ok(submit(a,ta,"Криптовалюта").status_code==201,"EXISTING_CRYPTO_METHOD_ACCEPTED_IN_SANDBOX")
    ok(submit(a,"bad").status_code==403,"WEB_CREATE_CSRF_BLOCK")
    no_origin=a.post("/api/web/bookings",json={"origin":"Vilnius","destination":"Kaunas"})
    ok(no_origin.status_code==403,"WEB_CREATE_ORIGIN_BLOCK")
    key="synthetic_duplicate_request_key_1234"
    initial=submit(a,ta,key=key)
    repeated=submit(a,ta,key=key)
    ok(initial.status_code==201 and repeated.status_code==200 and repeated.json["replayed"],
       "WEB_BOOKING_IDEMPOTENCY")
    changed=submit(a,ta,key=key,to="Warsaw")
    ok(changed.status_code==409,"REPLAY_WITH_CHANGED_ROUTE_DENIED")
    ok("telegram_id" not in one[0],"WEB_NOT_MAPPED_TO_ARBITRARY_TELEGRAM_USER")
print("WEB_IDENTITY_BOOKING_INTEGRATION_STAGING_PASSED")
print("NO_LIVE_USER_ORDER_DATABASE_PAYMENT_PROVIDER_USED")
