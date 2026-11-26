"""Isolated authenticated passenger order API; no payment provider imports."""
import hashlib
import json
import os
import time
import uuid

import psycopg
from pd_dispatch_persistent import validated_order, fingerprint
from pd_native_auth_postgres_session_lifecycle import _digest

def make_orders_app(next_app, database_url, *, clock=time.time):
    def app(environ, start_response):
        if environ.get("PATH_INFO") != "/native-orders":
            return next_app(environ, start_response)

        def reply(code, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            start_response(code, [("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "no-store"), ("Content-Length", str(len(body)))])
            return [body]

        if (os.getenv("PD_NATIVE_SMS_ISOLATED") != "YES"
                or os.getenv("PD_DISPATCH_STAGING_ONLY") != "1"
                or os.getenv("PD_PAYMENT_MODE") != "disabled"
                or os.getenv("PD_DISPATCH_PERSISTENT_QUEUE") != "1"
                or os.getenv("PD_DISPATCH_ORDERS_DATABASE_URL") != database_url):
            return reply("503 Service Unavailable", {"error":"orders_disabled"})
        method = environ.get("REQUEST_METHOD")
        if method not in ("GET", "POST"):
            return reply("405 Method Not Allowed", {"error":"method_not_allowed"})
        auth = environ.get("HTTP_AUTHORIZATION", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        digest = _digest(token)
        if not digest or any(c.isspace() for c in token):
            return reply("401 Unauthorized", {"error":"invalid_session"})
        try:
            with psycopg.connect(database_url, connect_timeout=4,
                                 options="-c statement_timeout=4000") as db:
                session = db.execute(
                    "SELECT user_id,server_role FROM public.pd_validate_native_session(%s,%s)",
                    (digest, int(clock()))).fetchone()
                if not session:
                    return reply("401 Unauthorized", {"error":"invalid_session"})
                uid, role = session
                if role != "passenger":
                    return reply("403 Forbidden", {"error":"passenger_required"})
                # Explicit migration is required; no runtime schema changes.
                if method == "GET":
                    rows = db.execute("""SELECT o.id,o.origin,o.destination,o.trip_date,
                        o.trip_time,o.status FROM public.pd_dispatch_orders o
                        JOIN public.pd_native_order_owners n ON n.order_id=o.id
                        WHERE n.user_id=%s ORDER BY o.created_at DESC LIMIT 100""",
                        (uid,)).fetchall()
                    return reply("200 OK", {"payment_mode":"disabled","orders":[
                        dict(zip(("order_id","from","to","trip_date","trip_time","status"),
                                 (str(r[0]), *r[1:]))) for r in rows]})
                try:
                    length = int(environ.get("CONTENT_LENGTH", "0"))
                    if not 0 < length <= 8192 or environ.get("CONTENT_TYPE","").split(";")[0] != "application/json":
                        raise ValueError()
                    data = json.loads(environ["wsgi.input"].read(length))
                    if not isinstance(data, dict) or set(data) != {"request_id","from","to","trip_date","trip_time"}:
                        raise ValueError()
                    request_id = str(uuid.UUID(data.pop("request_id")))
                    scoped = hashlib.sha256((str(uid)+":"+request_id).encode()).hexdigest()
                    values = validated_order(dict(data, source="android", source_order_id=scoped))
                except (ValueError, TypeError, KeyError, AttributeError):
                    return reply("400 Bad Request", {"error":"invalid_order"})
                source, original, origin, destination, date, clock_time = values
                fp = fingerprint(values)
                order_id = str(uuid.uuid4())
                inserted = db.execute("""INSERT INTO public.pd_dispatch_orders
                    (id,source,source_order_id,fingerprint,origin,destination,trip_date,trip_time)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(source,source_order_id) DO NOTHING RETURNING id""",
                    (order_id,source,original,fp,origin,destination,date,clock_time)).fetchone()
                if inserted:
                    db.execute("INSERT INTO public.pd_native_order_owners(order_id,user_id) VALUES (%s,%s)",
                               (order_id,uid))
                    status = "requested"
                else:
                    existing = db.execute("""SELECT o.id,o.fingerprint,o.status
                        FROM public.pd_dispatch_orders o JOIN public.pd_native_order_owners n ON n.order_id=o.id
                        WHERE o.source=%s AND o.source_order_id=%s AND n.user_id=%s""",
                        (source,original,uid)).fetchone()
                    if not existing or existing[1] != fp:
                        return reply("409 Conflict", {"error":"request_conflict"})
                    order_id, status = str(existing[0]), existing[2]
            return reply("201 Created" if inserted else "200 OK",
                         {"order_id":order_id,"status":status,"payment_mode":"disabled"})
        except psycopg.Error:
            return reply("503 Service Unavailable", {"error":"storage_unavailable"})
    return app
