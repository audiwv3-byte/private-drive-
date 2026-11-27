"""Isolated authenticated passenger order API; no payment provider imports."""
import hashlib
import json
import os
import time
import uuid

import psycopg
from pd_dispatch_persistent import validated_order, fingerprint
from pd_native_order_quote import validated_details
import pd_first_ride_wheel as wheel
from pd_native_auth_postgres_session_lifecycle import _digest

def make_orders_app(next_app, database_url, *, clock=time.time):
    def app(environ, start_response):
        path = environ.get("PATH_INFO")
        wheel_request = path == "/native-first-ride-wheel" and wheel.enabled()
        if path != "/native-orders" and not wheel_request:
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
        if method not in (("GET", "POST") if wheel_request else ("GET", "POST", "PATCH")):
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
                wheel_active = wheel.enabled()
                if wheel_request:
                    account = wheel.session_account(db, token, int(clock()))
                    if not account:
                        return reply("403 Forbidden", {"error":"verified_phone_required"})
                    result = wheel.reward(db, uid, int(clock()), spin=method == "POST")
                    db.commit()
                    return reply("200 OK", result)
                pilot_booking = wheel_active and role in ("pilot", "pilot_dispatcher")
                if role != "passenger" and not pilot_booking:
                    return reply("403 Forbidden", {"error":"passenger_required"})
                # Explicit migration is required; no runtime schema changes.
                if method == "GET":
                    # Existing read-only deployments may only have the original history grant.
                    quotes_readable = db.execute("""SELECT has_table_privilege(
                        to_regclass('public.pd_native_order_quotes'), 'SELECT')""").fetchone()[0]
                    if not quotes_readable:
                        rows = db.execute("""SELECT o.id,o.origin,o.destination,o.trip_date,o.trip_time,o.status
                            FROM public.pd_dispatch_orders o JOIN public.pd_native_order_owners n ON n.order_id=o.id
                            WHERE n.user_id=%s ORDER BY o.created_at DESC LIMIT 100""", (uid,)).fetchall()
                        return reply("200 OK", {"payment_mode":"disabled","orders":[
                            dict(zip(("order_id","from","to","trip_date","trip_time","status"),
                                     (str(r[0]), *r[1:]))) for r in rows]})
                    if wheel_active:
                        discounts = dict(db.execute("""
                            SELECT r.order_id,r.percent FROM public.pd_first_ride_rewards r
                            WHERE r.user_id=%s AND r.order_id IS NOT NULL
                        """, (uid,)).fetchall())
                    else:
                        discounts = {}
                    rows = db.execute("""SELECT o.id,o.origin,o.destination,o.trip_date,
                        o.trip_time,o.status,q.details,q.quoted_total_cents,q.quote_required
                        FROM public.pd_dispatch_orders o
                        JOIN public.pd_native_order_owners n ON n.order_id=o.id
                        LEFT JOIN public.pd_native_order_quotes q ON q.order_id=o.id
                        WHERE n.user_id=%s ORDER BY o.created_at DESC LIMIT 100""",
                        (uid,)).fetchall()
                    return reply("200 OK", {"payment_mode":"disabled","orders":[
                        {"order_id":str(r[0]),"from":r[1],"to":r[2],
                         "trip_date":r[3],"trip_time":r[4],"status":r[5],
                         "details":r[6],"quoted_total_cents":wheel.discounted_cents(r[7], discounts.get(r[0])),
                         "quote_required":r[8] if r[8] is not None else True,
                         "currency":"EUR"} for r in rows]})
                if method == "PATCH":
                    # Only the order owner may cancel; never invent a local
                    # cancellation or overwrite an underway/completed trip.
                    try:
                        length = int(environ.get("CONTENT_LENGTH", "0"))
                        if (not 0 < length <= 512
                                or environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json"):
                            raise ValueError()
                        payload = json.loads(environ["wsgi.input"].read(length))
                        if not isinstance(payload, dict) or set(payload) != {"order_id", "action"}:
                            raise ValueError()
                        if payload["action"] != "cancel":
                            raise ValueError()
                        order_id = str(uuid.UUID(payload["order_id"]))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        return reply("400 Bad Request", {"error": "invalid_cancel"})
                    cancelled = db.execute("""
                        UPDATE public.pd_dispatch_orders AS o SET status='cancelled'
                        FROM public.pd_native_order_owners AS n
                        WHERE o.id=%s AND n.order_id=o.id AND n.user_id=%s
                          AND o.status IN ('requested', 'assigned', 'approaching')
                        RETURNING o.id, o.status
                    """, (order_id, uid)).fetchone()
                    if not cancelled:
                        current = db.execute("""
                            SELECT o.status FROM public.pd_dispatch_orders AS o
                            JOIN public.pd_native_order_owners AS n ON n.order_id=o.id
                            WHERE o.id=%s AND n.user_id=%s
                        """, (order_id, uid)).fetchone()
                        if not current:
                            return reply("404 Not Found", {"error": "order_not_found"})
                        if current[0] != "cancelled":
                            return reply("409 Conflict", {"error": "cannot_cancel_active_trip"})
                    db.commit()
                    return reply("200 OK", {"order_id": order_id,
                        "status": "cancelled", "payment_mode": "disabled"})
                try:
                    length = int(environ.get("CONTENT_LENGTH", "0"))
                    if not 0 < length <= 8192 or environ.get("CONTENT_TYPE","").split(";")[0] != "application/json":
                        raise ValueError()
                    data = json.loads(environ["wsgi.input"].read(length))
                    required = {"request_id","from","to","trip_date","trip_time"}
                    if not isinstance(data, dict) or not required.issubset(data) or (
                            set(data) - required - {"details"}):
                        raise ValueError()
                    request_id = str(uuid.UUID(data.pop("request_id")))
                    submitted_details = data.pop("details", None)
                    scoped = hashlib.sha256((str(uid)+":"+request_id).encode()).hexdigest()
                    values = validated_order(dict(data, source="android", source_order_id=scoped))
                    quote = (validated_details(submitted_details, origin=data["from"],
                                               destination=data["to"])
                             if submitted_details is not None else None)
                except (ValueError, TypeError, KeyError, AttributeError):
                    return reply("400 Bad Request", {"error":"invalid_order"})
                source, original, origin, destination, date, clock_time = values
                # Bind quote-relevant inputs to the idempotency fingerprint.
                # Existing five-field callers keep the previous fingerprint.
                fp = fingerprint(values) if quote is None else fingerprint(
                    [*values, quote])
                order_id = str(uuid.uuid4())
                eligible = wheel_active and wheel.prepare_order(db, uid)
                inserted = db.execute("""INSERT INTO public.pd_dispatch_orders
                    (id,source,source_order_id,fingerprint,origin,destination,trip_date,trip_time)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(source,source_order_id) DO NOTHING RETURNING id""",
                    (order_id,source,original,fp,origin,destination,date,clock_time)).fetchone()
                if inserted:
                    db.execute("INSERT INTO public.pd_native_order_owners(order_id,user_id) VALUES (%s,%s)",
                               (order_id,uid))
                    if quote is not None:
                        db.execute("""INSERT INTO public.pd_native_order_quotes
                            (order_id,details,quoted_total_cents,quote_required)
                            VALUES (%s,%s::jsonb,%s,%s)""",
                            (order_id,json.dumps({key: quote[key] for key in (
                                "ride_type","round_trip","extras","preferences")},
                                ensure_ascii=False),
                             quote["quoted_total_cents"],quote["quote_required"]))
                    status = "requested"
                    discount = wheel.redeem(db, uid, order_id, eligible=eligible) if wheel_active else None
                else:
                    existing = db.execute("""SELECT o.id,o.fingerprint,o.status
                        FROM public.pd_dispatch_orders o JOIN public.pd_native_order_owners n ON n.order_id=o.id
                        WHERE o.source=%s AND o.source_order_id=%s AND n.user_id=%s""",
                        (source,original,uid)).fetchone()
                    if not existing or existing[1] != fp:
                        return reply("409 Conflict", {"error":"request_conflict"})
                    order_id, status = str(existing[0]), existing[2]
                    discount = wheel.order_discount(db, order_id) if wheel_active else None
            cents = quote["quoted_total_cents"] if quote is not None else None
            result = dict(order_id=order_id, status=status, payment_mode="disabled",
                          quoted_total_cents=wheel.discounted_cents(cents, discount),
                          quote_required=quote["quote_required"] if quote is not None else True,
                          currency="EUR")
            if discount is not None:
                result["discount_percent"] = discount
            return reply("201 Created" if inserted else "200 OK",
                         result)
        except psycopg.Error:
            return reply("503 Service Unavailable", {"error":"storage_unavailable"})
    return app
