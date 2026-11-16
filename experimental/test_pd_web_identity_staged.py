"""Disposable identity prototype tests; no real users, emails, orders or payments."""
import importlib.util,pathlib,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("pd_staged",ROOT/"experimental/pd_web_identity_staged.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
origin="https://wilsonpark.pythonanywhere.com"
clock=[2000000000]
notified=[]
def deliver(email,code):notified.append((email,code))
with tempfile.TemporaryDirectory(prefix="pd-web-identity-test-") as td:
    app=m.create_isolated_app(pathlib.Path(td)/"web.sqlite","test-signing-key-"+("x"*48),deliver,clock=lambda:clock[0],allowed_origin=origin)
    def token(client):
        res=client.get("/api/web/csrf")
        assert res.status_code==200
        return res.json["csrf_token"]
    def post(client,path,data,csrf="",site=origin):
        return client.post(path,json=data,headers={"Origin":site,"X-CSRF-Token":csrf})
    c1=app.test_client()
    assert c1.get("/api/web/me").status_code==401
    csrf=token(c1)
    res=post(c1,"/api/web/start",{"email":"pilot@example.test"},site="https://evil.example",csrf=csrf)
    assert res.status_code==403 and notified==[]
    print("PASS CROSS_ORIGIN_BLOCKED")
    assert post(c1,"/api/web/start",{"email":"pilot@example.test"},csrf="bad").status_code==403
    print("PASS CSRF_GUARD")
    assert post(c1,"/api/web/start",{"email":"pilot@example.test"},csrf=csrf).status_code==200
    assert notified[0][0]=="pilot@example.test"
    assert c1.get("/api/web/me").status_code==401
    res=post(c1,"/api/web/verify",{"code":"000000" if notified[-1][1]!="000000" else "999999"},csrf=csrf)
    assert res.status_code==400
    res=post(c1,"/api/web/verify",{"code":notified[-1][1]},csrf=csrf)
    assert res.status_code==200
    assert c1.get("/api/web/me").json["role"]=="passenger"
    assert c1.get("/api/web/me").json["id"].startswith("web_")
    assert "telegram_id" not in c1.get("/api/web/me").json
    print("PASS WEB_IDENTITY_CREATED_NO_TELEGRAM_IMPERSONATION")
    cookies=c1.get("/api/web/csrf").headers.getlist("Set-Cookie")
    assert all("Secure" in header and "HttpOnly" in header and "SameSite=Lax" in header for header in cookies if header.startswith("pd_web_session_staged"))
    assert "no-store" in c1.get("/api/web/me").headers.get("Cache-Control","")
    print("PASS SECURE_HTTPONLY_SAMESITE_AND_NOSTORE")
    c2=app.test_client()
    assert c2.get("/api/web/me").status_code==401
    csrf2=token(c2)
    assert post(c2,"/api/web/start",{"email":"other@example.test"},csrf=csrf2).status_code==200
    assert post(c2,"/api/web/verify",{"code":notified[-1][1]},csrf=csrf2).status_code==200
    assert c2.get("/api/web/me").json["id"]!=c1.get("/api/web/me").json["id"]
    print("PASS TWO_USERS_ISOLATED_NO_SHARED_WEB_SESSION")
    c1_new_csrf=token(c1)
    assert post(c1,"/api/web/logout",{},csrf="forged").status_code==403
    assert c1.get("/api/web/me").status_code==200
    assert post(c1,"/api/web/logout",{},csrf=c1_new_csrf).status_code==200
    assert c1.get("/api/web/me").status_code==401
    print("PASS LOGOUT_AND_CSRF_PROTECTION")
    c3=app.test_client(); t3=token(c3)
    assert post(c3,"/api/web/start",{"email":"expired@example.test"},csrf=t3).status_code==200
    expired=notified[-1][1];clock[0]+=601
    assert post(c3,"/api/web/verify",{"code":expired},csrf=t3).status_code==400
    print("PASS EXPIRED_OTP_REJECTED")
    c4=app.test_client(); t4=token(c4)
    for i in range(3):
        assert post(c4,"/api/web/start",{"email":"limited@example.test"},csrf=t4).status_code==200
    assert post(c4,"/api/web/start",{"email":"limited@example.test"},csrf=t4).status_code==429
    print("PASS RATE_LIMITS")
    c5=app.test_client(); t5=token(c5)
    assert post(c5,"/api/web/start",{"email":"guess@example.test"},csrf=t5).status_code==200
    correct=notified[-1][1]
    wrong="000000" if correct!="000000" else "999999"
    for i in range(5):
        assert post(c5,"/api/web/verify",{"code":wrong},csrf=t5).status_code==400
    assert post(c5,"/api/web/verify",{"code":correct},csrf=t5).status_code==429
    print("PASS OTP_GUESS_LOCKOUT")
print("WEB_LOGIN_ISOLATED_TESTS_PASSED")
print("NO_EXISTING_USERS_ORDERS_OR_PAYMENT_DATA_TOUCHED")
