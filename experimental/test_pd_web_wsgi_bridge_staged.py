"""Offline WSGI bridge tests with two synthetic Flask apps and temp SQLite.

Existing Telegram auth/order endpoints remain untouched; web login and fake
booking are isolated in separate Flask instance. No PythonAnywhere writes.
"""
import pathlib,sys,tempfile
from flask import Flask,jsonify,request
from werkzeug.test import Client
from werkzeug.wrappers import Response
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from pd_web_wsgi_bridge_staged import create_staged_wsgi

ORIGIN="https://wilsonpark.pythonanywhere.com"
def require(value,name):
    if not value:raise AssertionError(name)
    print("PASS",name,flush=True)
with tempfile.TemporaryDirectory(prefix="pd-wsgi-stage-") as tmp:
    legacy=Flask("synthetic_legacy_telegram")
    legacy.config.update(SECRET_KEY="not-a-real-secret-"+("f"*40),
                         SESSION_COOKIE_NAME="legacy_telegram_session")
    @legacy.get("/")
    def home():return "PRIVATE DRIVE original passenger app",200
    @legacy.get("/api/me")
    def original_me():return jsonify(error="Signed Telegram initData required"),401
    @legacy.post("/api/order")
    def original_order():return jsonify(error="Telegram authentication required"),401
    @legacy.get("/api/admin/orders")
    def original_admin():return jsonify(error="Admin not authorized"),401
    saved_wsgi=legacy.wsgi_app
    notifications=[]
    combined,web=create_staged_wsgi(
        legacy,str(pathlib.Path(tmp)/"web.sqlite"),
        "offline-only-web-secret-"+("x"*48),
        lambda email,code:notifications.append((email,code)),
        allowed_origin=ORIGIN)
    require(legacy.wsgi_app.__self__ is saved_wsgi.__self__ and legacy.wsgi_app.__func__ is saved_wsgi.__func__,"ORIGINAL_LEGACY_WSGI_UNCHANGED")
    c=Client(combined,Response,use_cookies=True)
    def get(path):return c.get(path,base_url=ORIGIN)
    def post(path,**kwargs):return c.post(path,base_url=ORIGIN,**kwargs)
    status=c.get("/")
    require(status.status_code==200 and b"original passenger app" in status.data,
            "LEGACY_PASSENGER_HTML_UNCHANGED")
    require(c.get("/api/me").status_code==401,"LEGACY_TELEGRAM_AUTH_UNCHANGED")
    require(c.post("/api/order",json={}).status_code==401,"LEGACY_ORDER_CREATE_UNCHANGED")
    require(c.get("/api/admin/orders").status_code==401,"LEGACY_ADMIN_GUARD_UNCHANGED")
    require(c.get("/api/web/me").status_code==404 or c.get("/api/web/me").status_code==401,
            "WEB_API_NOT_CONFUSED_WITH_TELEGRAM")
    csrf=c.get("/api/web/csrf")
    require(csrf.status_code==200,"WEB_CSRF_ROUTE_INDEPENDENT")
    web_cookie=csrf.headers.get("Set-Cookie","")
    require("pd_web_session_staged=" in web_cookie and "HttpOnly" in web_cookie and "Secure" in web_cookie,
            "WEB_SESSION_SEPARATE_SECURE_COOKIE")
    require("legacy_telegram_session=" not in web_cookie,"LEGACY_COOKIE_NOT_OVERWRITTEN")
    token=csrf.json["csrf_token"]
    headers={"Origin":ORIGIN,"X-CSRF-Token":token}
    require(c.post("/api/web/start",json={"email":"isolated@example.test"},headers=headers).status_code==200,
            "WEB_OTP_STARTED_ISOLATED")
    code=notifications[-1][1]
    require(c.post("/api/web/verify",json={"code":code},headers=headers).status_code==200,
            "WEB_OTP_CONFIRMED_ISOLATED")
    me=c.get("/api/web/me")
    require(me.status_code==200 and me.json["role"]=="passenger","WEB_PASSENGER_LOGIN")
    require(c.get("/api/me").status_code==401,"WEB_COOKIE_DOES_NOT_GRANT_TELEGRAM_ID")
    require(c.get("/api/admin/orders").status_code==401,"WEB_COOKIE_DOES_NOT_GRANT_ADMIN")
    token=c.get("/api/web/csrf").json["csrf_token"]
    headers={"Origin":ORIGIN,"X-CSRF-Token":token}
    booking=c.post("/api/web/bookings",headers=headers,json={
        "origin":"Vilnius","destination":"Kaunas","request_key":"synthetic_12345678909876",
        "payment_method":"Банковский перевод"})
    require(booking.status_code==201,"WEB_BOOKING_USES_ONLY_TEMP_DB")
    bid=booking.json["id"]
    require(c.get(f"/api/web/bookings/{bid}/payment").json["checkout_enabled"] is False,
            "WEB_PAYMENT_DISABLED_UNTIL_PROVIDER_TEST")
    require(c.post("/api/order",json={"id":bid}).status_code==401,
            "STAGED_WEB_BOOKING_CANNOT_BYPASS_REAL_TELEGRAM_ORDER_ENDPOINT")
    require(c.get("/api/admin/orders").status_code==401,"ADMIN_UNCHANGED_AFTER_WEB_BOOKING")
print("WEB_WSGI_STAGED_INTEGRATION_TESTS_PASS")
print("NO_LIVE_SERVER_ORDERS_USERS_OR_PAYMENTS")
