import json
import os
import secrets
import ssl
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from ops.qa.qa42_device_tls import generate
from ops.qa.qa42_local_kit import make_tls_server, prepare


def test_local_kit(monkeypatch, tmp_path):
    monkeypatch.setenv("PD_QA42_LOCAL","YES")
    from ops.qa.qa42_mobile_login import new_codes
    codes = new_codes()
    password = secrets.token_urlsafe(24)
    app,tokens,telegram_token,csrf = prepare(mobile_codes=codes, dispatcher_password=password)
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    c=Client(app,Response)
    for role in ("passenger","pilot"):
        response=c.post("/native-auth/session",headers={"Authorization":"Bearer "+tokens[role]})
        assert response.status_code==200
        assert response.json["role"]==role
    assert c.post("/native-auth/session").status_code==401
    assert c.post("/native-auth/request-code",json={}).status_code==403
    for phone,role in (("+12025550101","passenger"),("+12025550102","pilot")):
        req=c.post("/native-auth/request-code",json={"channel":"phone","destination":phone})
        assert req.status_code==202
        cid=req.json["challenge_id"]
        assert c.post("/native-auth/verify-code",json={"challenge_id":cid,"code":"xxxxxx"}).status_code==401
        verified=c.post("/native-auth/verify-code",json={"challenge_id":cid,"code":codes[phone]})
        assert verified.status_code==200 and verified.json["role"]==role
        assert c.post("/native-auth/verify-code",json={"challenge_id":cid,"code":codes[phone]}).status_code==401
        assert c.post("/native-auth/session",headers={"Authorization":"Bearer "+verified.json["access_token"]}).json["role"]==role
    print("PASS existing mobile OTP contract, server roles, single use and session validation")
    certs = generate("127.0.0.1", tmp_path / "tls")
    server = make_tls_server(
        "127.0.0.1", certs / "server.pem", certs / "server.key", app, port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"https://127.0.0.1:{server.server_port}"
        with pytest.raises(URLError) as error:
            urlopen(origin + "/dispatch/login", timeout=5)
        assert isinstance(error.value.reason, ssl.SSLCertVerificationError)

        trust = ssl.create_default_context(cafile=str(certs / "ca.pem"))
        with urlopen(origin + "/dispatch/login", context=trust, timeout=5) as result:
            assert result.status == 200
            assert "Secure" in result.headers["Set-Cookie"]
        session = Request(
            origin + "/native-auth/session",
            data=b"{}",
            headers={"Authorization": "Bearer " + tokens["pilot"]},
        )
        with urlopen(session, context=trust, timeout=5) as result:
            assert json.load(result)["role"] == "pilot"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    print("PASS trusted TLS dispatcher and native session; untrusted TLS rejected")
    assert c.get("/payment/paysera").status_code==403
    assert c.get("/dispatch/orders/state").status_code==401
    import re, uuid
    from werkzeug.test import Client
    browser = Client(app,Response)
    origin = "https://127.0.0.1"
    login = browser.get("/dispatch/login",base_url=origin)
    assert login.status_code==200
    assert "Secure" in login.headers["Set-Cookie"] and "HttpOnly" in login.headers["Set-Cookie"] and "SameSite=Strict" in login.headers["Set-Cookie"]
    csrf_login = re.search(r'name="csrf" value="([^"]+)"',login.get_data(as_text=True)).group(1)
    assert browser.post("/dispatch/login",base_url=origin,data={"password":password}).status_code==403
    assert browser.post("/dispatch/login",base_url=origin,data={"password":password,"csrf":csrf_login}).status_code in (302,303)
    page=browser.get("/dispatch",base_url=origin)
    assert page.status_code==200 and "no-store" in page.headers["Cache-Control"]
    csrf_session = re.search(r'name="csrf" value="([^"]+)"',page.get_data(as_text=True))
    if csrf_session is None:
        from itsdangerous import URLSafeTimedSerializer
        from flask.sessions import SecureCookieSessionInterface
        from flask import Flask
        f=Flask("test"); f.secret_key=os.environ["PD_DISPATCH_SESSION_SECRET"]
        csrf_value=SecureCookieSessionInterface().get_signing_serializer(f).loads(browser.get_cookie("pd_qa42_session",path="/dispatch").value)["pd_dispatch_csrf"]
    else:
        csrf_value=csrf_session.group(1)
    h={"Authorization":"Bearer "+tokens["passenger"]}
    order=c.post("/native-orders",headers=h,json={"request_id":str(uuid.uuid4()),"from":"QA42 A","to":"QA42 B","trip_date":"2030-01-01","trip_time":"12:00"})
    assert order.status_code==201,order.json
    oid=order.json["order_id"]
    assert browser.get("/dispatch/orders/state",base_url=origin).json["orders"][0]["id"]==oid
    path="/dispatch/orders/"+oid+"/assign"
    assert browser.post(path,base_url=origin,data={"pilot_id":"qa39-pilot"}).status_code==403
    assigned=browser.post(path,base_url=origin,data={"pilot_id":"qa39-pilot","csrf":csrf_value})
    assert assigned.status_code==200,assigned.json
    gps="/native-pilot-orders/"+oid+"/gps"
    stamp=int(time.time())
    fix=c.post(gps,headers={"Authorization":"Bearer "+tokens["pilot"]},json={"enabled":True,"captured_at":stamp,"latitude":54.6872,"longitude":25.2797})
    assert fix.status_code==200,fix.json
    read=browser.get("/dispatch/orders/"+oid+"/gps",base_url=origin)
    assert read.status_code==200,read.json
    assert browser.post("/dispatch/logout",base_url=origin,data={"csrf":csrf_value}).status_code in (302,303)
    assert browser.get("/dispatch/orders/state",base_url=origin).status_code==401
    print("PASS dispatcher cookie login, CSRF, order assignment, GPS read and logout")
    with pytest.raises(RuntimeError,match="Fresh"):
        prepare()
    print("PASS local kit bootstrap, scoped sessions, blocked external services and fresh DB gate")
