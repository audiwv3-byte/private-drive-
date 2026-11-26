"""PRIVATE DRIVE persistent dispatcher order intake.

Designed for isolated stage-to-real migration. No QA tokens, no client-chosen
roles and no real payments. Requires separate, durable PostgreSQL and a private
server-to-server HMAC key; remains disabled until deliberately configured.
"""
from datetime import date as calendar_date
import hashlib
import hmac
import json
import os
import re
import time
import uuid

from flask import jsonify, request

MAX_BYTES = 8192
SOURCES = frozenset({"website", "android", "ios", "telegram_miniapp", "telegram_bot"})


def enabled():
    dsn = os.environ.get("PD_DISPATCH_ORDERS_DATABASE_URL", "")
    return (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.environ.get("PD_DISPATCH_PERSISTENT_QUEUE") == "1"
            and os.environ.get("PD_PAYMENT_MODE") == "disabled"
            and dsn.startswith(("postgresql://", "postgres://")))


def ingest_enabled():
    # Native orders write through their authenticated API directly.
    # Reading the dispatcher queue must not enable the separate import route.
    return enabled() and len(os.environ.get("PD_DISPATCH_ORDERS_INGEST_SECRET", "")) >= 32



def order_gps_enabled():
    """Fail-closed QA27 display gate for the browser dispatcher."""
    if not (enabled() and os.environ.get("PD_QA27_GPS") == "1"
            and os.environ.get("PD_NATIVE_SMS_LIVE") == "NO"
            and os.environ.get("PD_PAYMENT_MODE") == "disabled"):
        return False
    from psycopg import ProgrammingError
    from psycopg.conninfo import conninfo_to_dict

    try:
        fields = conninfo_to_dict(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"])
    except ProgrammingError:
        return False
    # Reject alternate hosts, services and libpq routing overrides.
    return (fields.keys() <= {"host", "port", "dbname", "user", "password"}
            and fields.get("host") == "127.0.0.1"
            and fields.get("port", "5432") == "5432"
            and fields.get("dbname") == "private_drive_test")


def verified_request(raw, headers, key, now=None):
    issued = headers.get("X-PD-Order-Timestamp", "")
    signature = headers.get("X-PD-Order-Signature", "")
    if not re.fullmatch(r"[0-9]{10,12}", issued) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        return False
    if abs((int(time.time()) if now is None else int(now)) - int(issued)) > 300:
        return False
    digest = hmac.new(key.encode(), issued.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def validated_order(data):
    if not isinstance(data, dict) or set(data) != {
            "source", "source_order_id", "from", "to", "trip_date", "trip_time"}:
        raise ValueError("invalid_order")
    source = data["source"]
    original = data["source_order_id"]
    if not isinstance(source, str) or source not in SOURCES or not isinstance(original, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", original):
        raise ValueError("invalid_source")
    origin, destination = data["from"], data["to"]
    if not isinstance(origin, str) or not isinstance(destination, str):
        raise ValueError("invalid_route")
    origin, destination = origin.strip(), destination.strip()
    if not 2 <= len(origin) <= 200 or not 2 <= len(destination) <= 200 or origin.casefold() == destination.casefold():
        raise ValueError("invalid_route")
    date, clock = data["trip_date"], data["trip_time"]
    if not isinstance(date, str) or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", date):
        raise ValueError("invalid_departure")
    if not isinstance(clock, str) or not re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", clock) or int(clock[:2]) > 23:
        raise ValueError("invalid_departure")
    calendar_date.fromisoformat(date)
    return source, original, origin, destination, date, clock


def fingerprint(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def register(app, authorized):
    def reply(body, status=200):
        response = jsonify(body)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        return response

    def connect():
        import psycopg
        return psycopg.connect(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"],
                               connect_timeout=4, options="-c statement_timeout=4000")

    @app.post("/v1/dispatch/orders/import")
    def import_order():
        if not ingest_enabled():
            return reply({"error":"persistent_queue_disabled"}, 503)
        if request.mimetype != "application/json" or request.content_length is None or not 0 < request.content_length <= MAX_BYTES:
            return reply({"error":"invalid_body"}, 400)
        raw = request.get_data(cache=False)
        if not verified_request(raw, request.headers, os.environ["PD_DISPATCH_ORDERS_INGEST_SECRET"]):
            return reply({"error":"unauthorized"}, 401)
        try:
            values = validated_order(json.loads(raw))
        except (ValueError, TypeError, UnicodeError) as exc:
            return reply({"error":"invalid_order"}, 400)
        source, original, origin, destination, date, clock = values
        digest = fingerprint(values)
        order_id = str(uuid.uuid4())
        status = "requested"
        try:
            with connect() as db:
                # The insert either wins once or retrieves an existing record.
                with db.cursor() as cur:
                    cur.execute("""INSERT INTO public.pd_dispatch_orders
                        (id,source,source_order_id,fingerprint,origin,destination,trip_date,trip_time)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(source,source_order_id) DO NOTHING
                        RETURNING id""", (order_id,source,original,digest,origin,destination,date,clock))
                    inserted = cur.fetchone()
                    if not inserted:
                        cur.execute("""SELECT id,fingerprint,status FROM public.pd_dispatch_orders
                            WHERE source=%s AND source_order_id=%s""", (source,original))
                        existing = cur.fetchone()
                        if not existing or existing[1] != digest:
                            return reply({"error":"source_order_conflict"}, 409)
                        order_id = str(existing[0])
                        status = existing[2]
            return reply({"order_id":order_id,"source":source,"source_order_id":original,
                          "status":status,"created":bool(inserted),"payment_mode":"disabled"}, 201 if inserted else 200)
        except Exception:
            app.logger.exception("Persistent dispatcher order store unavailable")
            return reply({"error":"storage_unavailable"},503)

    def dispatch_order_gps(order_id):
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        if not order_gps_enabled():
            return reply({"error": "gps_disabled"}, 503)
        try:
            with connect() as db:
                if db.execute("SELECT current_database()").fetchone()[0] != "private_drive_test":
                    return reply({"error": "gps_disabled"}, 503)
                result = db.execute(
                    "SELECT public.pd_qa27_dispatch_gps(%s, %s)",
                    (order_id, int(time.time())),
                ).fetchone()[0]
            status = {"order_not_found": 404}.get(result.get("error"), 200)
            return reply(result, status)
        except Exception as exc:
            app.logger.warning("Dispatcher GPS read unavailable (%s)", type(exc).__name__)
            return reply({"error": "storage_unavailable"}, 503)

    # QA25 already registers its authenticated GPS route. The standalone
    # browser dispatcher owns a different, cookie-session protected route.
    if app.name != "pd_qa25_wsgi":
        app.add_url_rule("/dispatch/orders/<uuid:order_id>/gps",
            endpoint="dispatch_order_gps", view_func=dispatch_order_gps, methods=["GET"])

    @app.get("/dispatch/orders/state")
    def order_state():
        if not authorized():
            return reply({"error":"unauthorized"},401)
        if not enabled():
            return reply({"error":"persistent_queue_disabled"},503)
        try:
            with connect() as db:
                rows = db.execute("""SELECT id,source,source_order_id,origin,destination,
                     trip_date,trip_time,status,created_at
                     FROM public.pd_dispatch_orders ORDER BY created_at DESC LIMIT 100""").fetchall()
            orders = [{"id":str(row[0]),"source":row[1],"source_order_id":row[2],
                       "origin":row[3],"destination":row[4],
                       "trip_date":row[5],"trip_time":row[6],
                       "status":row[7],"created_at":row[8].isoformat()} for row in rows]
            return reply({"orders":orders,"persistent":True})
        except Exception:
            app.logger.exception("Persistent dispatcher order read unavailable")
            return reply({"error":"storage_unavailable"},503)
