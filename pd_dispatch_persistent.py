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


def telegram_reference(uid, oid):
    return hashlib.sha256(f"miniapp:{uid}:{oid}".encode()).hexdigest()


def connect():
    import psycopg
    return psycopg.connect(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"],
                           connect_timeout=4, options="-c statement_timeout=4000")


def store_order(values, *, telegram_id=None, website_contact=None):
    """Insert a validated booking or return the matching earlier submission."""
    source, original, *route = values
    digest = fingerprint(values if website_contact is None else (*values, website_contact))
    with connect() as db:
        row = db.execute("""INSERT INTO public.pd_dispatch_orders
            (id,source,source_order_id,fingerprint,origin,destination,trip_date,trip_time,website_contact)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(source,source_order_id) DO NOTHING RETURNING id,status""",
            (uuid.uuid4(), source, original, digest, *route, website_contact)).fetchone()
        created = row is not None
        if created and telegram_id is not None:
            db.execute("INSERT INTO public.pd_telegram_order_owners(order_id,telegram_id) VALUES (%s,%s)",
                       (row[0], telegram_id))
        if not created:
            row = db.execute("""SELECT id,status,fingerprint FROM public.pd_dispatch_orders
                WHERE source=%s AND source_order_id=%s""", (source, original)).fetchone()
            if not row or row[2] != digest:
                raise ValueError("source_order_conflict")
    return dict(order_id=str(row[0]), source=source, source_order_id=original,
                status=row[1], created=created, payment_mode="disabled")


def register(app, authorized):
    def reply(body, status=200):
        response = jsonify(body)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        return response

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
        try:
            result = store_order(values)
        except ValueError:
            return reply({"error":"source_order_conflict"}, 409)
        except Exception:
            app.logger.exception("Persistent dispatcher order store unavailable")
            return reply({"error":"storage_unavailable"}, 503)
        return reply(result, 201 if result["created"] else 200)

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
        paginated = os.getenv("PD_QA36_PAGINATION") == "1" and order_gps_enabled()
        page=1
        mode="all"
        if paginated:
            try:
                page=int(request.args.get("page","1"))
                mode=request.args.get("filter","all")
                if not 1<=page<=10000 or mode not in ("all","new","active","done"):
                    raise ValueError()
            except ValueError:
                return reply({"error":"invalid_page"},400)
        try:
            with connect() as db:
                if paginated:
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    counts=db.execute("""SELECT count(*),count(*) FILTER(WHERE status='requested'),
                        count(*) FILTER(WHERE status IN ('assigned','approaching','arrived','underway')),
                        count(*) FILTER(WHERE status IN ('finished','cancelled')) FROM public.pd_dispatch_orders""").fetchone()
                    total=counts[("all","new","active","done").index(mode)]
                    page=min(page,max(1,(total+99)//100))
                qa33 = os.getenv("PD_QA33_TRIP") == "1" and order_gps_enabled()
                extra = ",waiting_seconds + CASE WHEN waiting_started_at IS NULL THEN 0 ELSE greatest(0,extract(epoch from now())::bigint-waiting_started_at) END, waiting_started_at IS NOT NULL, stop_charge_cents + CASE WHEN waiting_started_at IS NULL THEN 0 ELSE ((greatest(0,extract(epoch from now())::bigint-waiting_started_at)+59)/60)*25 END" if qa33 else ""
                rows = db.execute("""SELECT id,source,source_order_id,origin,destination,
                     trip_date,trip_time,status,created_at,website_contact""" + extra + """
                     FROM public.pd_dispatch_orders
                     WHERE (%s='all' OR (%s='new' AND status='requested') OR
                     (%s='active' AND status IN ('assigned','approaching','arrived','underway')) OR
                     (%s='done' AND status IN ('finished','cancelled')))
                     ORDER BY created_at DESC,id DESC LIMIT 100 OFFSET %s""",(mode,mode,mode,mode,(page-1)*100)).fetchall()
                quotes = {}
                if db.execute("SELECT has_table_privilege(to_regclass('public.pd_native_order_quotes'), 'SELECT')").fetchone()[0]:
                    quotes = {str(q[0]): (q[1], q[2]) for q in db.execute("SELECT order_id, details, quoted_total_cents FROM public.pd_native_order_quotes WHERE order_id = ANY(%s::uuid[])", ([str(row[0]) for row in rows],)).fetchall()}
            orders = [{"id":str(row[0]),"source":row[1],"source_order_id":row[2],
                       "origin":row[3],"destination":row[4],
                       "trip_date":row[5],"trip_time":row[6],
                       "status":row[7],"created_at":row[8].isoformat(),"website_contact":row[9]} for row in rows]
            for order in orders:
                if order["id"] in quotes:
                    details, cents = quotes[order["id"]]
                    if details.get("ride_type") in ("delivery", "jumpstart"):
                        order.update(service_type=details["ride_type"], service_notes=details.get("preferences", {}).get("wishes", ""), quoted_total_cents=cents)
            if qa33:
                for order,row in zip(orders,rows):
                    order.update(waiting_seconds=row[10],waiting_active=row[11],stop_charge_cents=row[12])
            result={"orders":orders,"persistent":True}
            if paginated:
                result.update(page=page,page_size=100,total=total,counts=dict(zip(("all","new","active","done"),counts)))
            return reply(result)
        except Exception:
            app.logger.exception("Persistent dispatcher order read unavailable")
            return reply({"error":"storage_unavailable"},503)
