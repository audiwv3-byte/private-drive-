"""STAGING ONLY: connect prototype web login to isolated passenger bookings.

This is NOT the production orders database, not mounted in the active Flask
application, and has no payment processing, notifications, or Telegram writes.
Do not ship until production identity/DB mapping reviewed and migrated safely.
"""
import hmac
import secrets
import sqlite3
from flask import jsonify,request,session

ALLOWED_METHODS=("Банковский перевод","Криптовалюта")
def add_staged_web_bookings(app,database,*,origin):
    def db():
        conn=sqlite3.connect(database)
        conn.row_factory=sqlite3.Row
        return conn
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS web_bookings_test(
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           owner_web_id TEXT NOT NULL,
           origin TEXT NOT NULL,
           destination TEXT NOT NULL,
           payment_method TEXT NOT NULL,
           status TEXT NOT NULL DEFAULT 'Новая',
           price_eur TEXT,
           payment_status TEXT NOT NULL DEFAULT 'Не оплачено',
           idempotency_key TEXT NOT NULL,
           UNIQUE(owner_web_id,idempotency_key),
           FOREIGN KEY(owner_web_id) REFERENCES web_users(web_id))""")
    def failure(msg,status):return jsonify(error=msg),status
    def user():
        ident=session.get("web_uid")
        if not ident:return None
        with db() as conn:
            return conn.execute("SELECT web_id FROM web_users WHERE web_id=?",(ident,)).fetchone()
    def guard():
        if request.headers.get("Origin")!=origin:return False
        a=request.headers.get("X-CSRF-Token","")
        b=session.get("csrf","")
        return bool(a and b and hmac.compare_digest(a,b))
    @app.get("/api/web/bookings")
    def web_bookings_list():
        row=user()
        if row is None:return failure("Authentication required",401)
        with db() as conn:
            data=conn.execute("""SELECT id,origin,destination,payment_method,status,
                              price_eur,payment_status FROM web_bookings_test
                              WHERE owner_web_id=? ORDER BY id DESC""",(row["web_id"],)).fetchall()
        return jsonify(orders=[dict(x) for x in data])
    @app.post("/api/web/bookings")
    def web_bookings_create():
        row=user()
        if row is None:return failure("Authentication required",401)
        if not guard():return failure("Invalid request token",403)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return failure("Invalid booking request",400)
        method=data.get("payment_method","Банковский перевод")
        if method not in ALLOWED_METHODS:return failure("Payment method unavailable",400)
        a=str(data.get("origin","")).strip()
        b=str(data.get("destination","")).strip()
        if not (2<=len(a)<=200 and 2<=len(b)<=200) or a.casefold()==b.casefold():
            return failure("Invalid route",400)
        key=data.get("request_key")
        if not isinstance(key,str) or not (16<=len(key)<=80) or not key.isascii() or not all(c.isalnum() or c in "_-" for c in key):
            return failure("Invalid request key",400)
        with db() as conn:
            old=conn.execute("SELECT * FROM web_bookings_test WHERE owner_web_id=? AND idempotency_key=?",
                             (row["web_id"],key)).fetchone()
            if old:
                if (old["origin"],old["destination"],old["payment_method"])!=(a,b,method):
                    return failure("Request key reused with different booking",409)
                return jsonify(id=old["id"],status=old["status"],replayed=True)
            cur=conn.execute("""INSERT INTO web_bookings_test
                (owner_web_id,origin,destination,payment_method,idempotency_key)
                VALUES(?,?,?,?,?)""",(row["web_id"],a,b,method,key))
            return jsonify(id=cur.lastrowid,status="Новая",replayed=False),201
    @app.get("/api/web/bookings/<int:booking_id>/payment")
    def web_booking_payment_status(booking_id):
        row=user()
        if row is None:return failure("Authentication required",401)
        with db() as conn:
            booking=conn.execute("""SELECT id,status,payment_status,payment_method,price_eur
                FROM web_bookings_test WHERE id=? AND owner_web_id=?""",
                (booking_id,row["web_id"])).fetchone()
        if not booking:return failure("Not found",404)
        return jsonify(dict(booking),checkout_enabled=False,
                       message="Payment integration not enabled in staging")
    return app
