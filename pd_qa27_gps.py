"""QA27 only: scoped GPS writes from native sessions, read by dispatcher."""
import os
import math
import time
from flask import jsonify, request
import psycopg
from psycopg.conninfo import conninfo_to_dict
from pd_native_auth_postgres_session_lifecycle import _digest
from pd_qa25_telegram_orders import safe

def register_gps(app, authorized, database_url, *, clock=time.time):
    fields = conninfo_to_dict(database_url)
    if fields.get("host") != "127.0.0.1" or fields.get("dbname") != "private_drive_test" or any(k in fields for k in ("hostaddr","service")):
        raise RuntimeError("QA27 requires local isolated PostgreSQL")

    def reply(data, status=200):
        response = jsonify(data)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        return response

    def enabled():
        return (os.getenv("PD_QA27_GPS") == "1" and os.getenv("PD_QA26_ASSIGNMENT") == "1"
            and os.getenv("PD_QA25_WSGI") == "1" and os.getenv("PD_NATIVE_PILOT_ASSIGNMENT") == "1"
            and os.getenv("PD_DISPATCH_ORDERS_DATABASE_URL") == database_url and safe())

    def query(sql, args):
        try:
            with psycopg.connect(database_url, connect_timeout=4, options="-c statement_timeout=4000") as db:
                if db.execute("SELECT current_database()").fetchone()[0] != "private_drive_test":
                    return reply({"error":"gps_disabled"},503)
                result = db.execute(sql,args).fetchone()[0]
            return reply(result, {"invalid_session":401,"pilot_required":403,"order_not_found":404,
                 "inactive_order":409,"stale_fix":409,"invalid_fix":400}.get(result.get("error"),200))
        except psycopg.Error:
            return reply({"error":"storage_unavailable"},503)

    @app.post("/native-pilot-orders/<uuid:oid>/gps")
    def write_gps(oid):
        if not enabled(): return reply({"error":"gps_disabled"},503)
        auth = request.headers.get("Authorization","")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        digest = _digest(token)
        if not digest or any(c.isspace() for c in token): return reply({"error":"invalid_session"},401)
        if request.mimetype != "application/json" or request.content_length is None or not 0 < request.content_length <= 1024:
            return reply({"error":"invalid_fix"},400)
        data = request.get_json(silent=True)
        if not isinstance(data,dict) or type(data.get("enabled")) is not bool or type(data.get("captured_at")) is not int:
            return reply({"error":"invalid_fix"},400)
        enabled_fix = data["enabled"]
        expected = {"enabled","captured_at","latitude","longitude"} if enabled_fix else {"enabled","captured_at"}
        if set(data) != expected or not 0 < data["captured_at"] < 2**63:
            return reply({"error":"invalid_fix"},400)
        lat,lon = data.get("latitude"),data.get("longitude")
        if enabled_fix:
            if any(type(x) not in (int,float) or not -limit <= x <= limit or not math.isfinite(x) for x,limit in ((lat,90),(lon,180))):
                return reply({"error":"invalid_fix"},400)
        return query("SELECT public.pd_qa27_write_gps(%s,%s,%s,%s,%s,%s,%s)",
                     (digest,oid,enabled_fix,lat,lon,data["captured_at"],int(clock())))

    @app.get("/dispatch/orders/<uuid:oid>/gps")
    def read_gps(oid):
        if not authorized(): return reply({"error":"unauthorized"},401)
        if not enabled(): return reply({"error":"gps_disabled"},503)
        return query("SELECT public.pd_qa27_dispatch_gps(%s,%s)",(oid,int(clock())))
