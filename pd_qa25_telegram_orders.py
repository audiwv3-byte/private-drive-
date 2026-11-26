"""QA-only Telegram order intake into the shared dispatcher queue."""
import hashlib
import os
import re
import uuid

from flask import jsonify, request
from pd_dispatch_persistent import enabled, validated_order, fingerprint
from pd_qa_order_details import normalize_details

def active():
    return os.getenv("PD_QA25_WSGI") == "1"

def safe():
    return enabled() and os.getenv("PD_NATIVE_SMS_ISOLATED") == "YES" and os.getenv("PD_NATIVE_SMS_LIVE") == "NO"

def telegram_order(uid, data):
    if not safe():
        return jsonify(error="orders_disabled"), 503
    if not isinstance(data, dict):
        return jsonify(error="invalid_order"), 400
    if data.get("payment_method", "Наличными") != "Наличными":
        return jsonify(error="payment_disabled"), 503
    key = data.get("request_key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
        return jsonify(error="request_key_required"), 400
    scoped = hashlib.sha256((str(uid)+":"+key).encode()).hexdigest()
    try:
        values = validated_order(dict(source="telegram_miniapp", source_order_id=scoped,
            **{"from":data.get("origin"),"to":data.get("destination")},
            trip_date=data.get("trip_date"),trip_time=data.get("trip_time")))
    except (ValueError, TypeError):
        return jsonify(error="invalid_order"), 400
    import json
    # Legacy Mini App booking form uses details/roundtrip; normalize into the
    # same typed, payment-free JSONB contract as Android.
    try:
        details = dict(data.get("booking_details") or {})
        if "roundtrip" in data: details["round_trip"] = data["roundtrip"]
        if "passengers" in data: details["passengers"] = data["passengers"]
        if "luggage" in data: details["luggage"] = data["luggage"]
        if "extras" in data: details["extras"] = data["extras"]
        if "details" in data: details["wishes"] = data["details"]
        details = normalize_details(details)
    except (TypeError, ValueError):
        return jsonify(error="invalid_booking_details"), 400
    digest = fingerprint((values, json.dumps(data, sort_keys=True, ensure_ascii=False)))
    oid = str(uuid.uuid4())
    qa26 = os.getenv("PD_QA26_ASSIGNMENT") == "1"
    status = "requested"
    import psycopg
    try:
        with psycopg.connect(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"], connect_timeout=4) as db:
            row = db.execute("""INSERT INTO public.pd_dispatch_orders
                (id,source,source_order_id,fingerprint,origin,destination,trip_date,trip_time,booking_details)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(source,source_order_id) DO NOTHING RETURNING id""",
                (oid,values[0],values[1],digest,*values[2:],json.dumps(details,ensure_ascii=False))).fetchone()
            if row and qa26:
                db.execute("INSERT INTO public.pd_telegram_order_owners(order_id,telegram_id) VALUES (%s,%s)", (oid,uid))
            if not row:
                old = db.execute("""SELECT id,fingerprint,status FROM public.pd_dispatch_orders
                    WHERE source=%s AND source_order_id=%s""", values[:2]).fetchone()
                if not old or old[1] != digest:
                    return jsonify(error="request_conflict"), 409
                oid = str(old[0])
                status = old[2]
                if qa26 and not db.execute("SELECT 1 FROM public.pd_telegram_order_owners WHERE order_id=%s AND telegram_id=%s",(oid,uid)).fetchone():
                    return jsonify(error="request_conflict"), 409
        return jsonify(ok=True,order_id=oid,status=status if qa26 else "Новая",price="",replayed=not bool(row))
    except psycopg.Error:
        return jsonify(error="storage_unavailable"), 503

def telegram_history(uid):
    """One PostgreSQL ownership contract for QA25 and the real Mini App WSGI."""
    if not safe() or os.getenv("PD_QA26_ASSIGNMENT") != "1":
        return jsonify(error="orders_disabled"), 503
    import psycopg
    try:
        with psycopg.connect(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"],
                            connect_timeout=4, options="-c statement_timeout=4000") as db:
            rows = db.execute("""SELECT o.id,o.origin,o.destination,o.trip_date,
                o.trip_time,o.status,o.booking_details FROM public.pd_dispatch_orders o
                JOIN public.pd_telegram_order_owners t ON t.order_id=o.id
                WHERE t.telegram_id=%s ORDER BY o.created_at DESC LIMIT 100""", (uid,)).fetchall()
        response = jsonify(orders=[dict(zip(
            ("order_id","origin","destination","trip_date","trip_time","status","booking_details"),
            (str(row[0]),*row[1:]))) for row in rows])
        response.headers["Cache-Control"] = "private, no-store"
        return response
    except psycopg.Error:
        return jsonify(error="storage_unavailable"), 503
