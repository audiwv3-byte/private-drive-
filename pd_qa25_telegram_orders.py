"""QA-only Telegram order intake into the shared dispatcher queue."""
import hashlib
import os
import re
import uuid

from flask import jsonify, request
from pd_dispatch_persistent import enabled, validated_order, fingerprint

def active():
    return os.getenv("PD_QA25_WSGI") == "1"

def safe():
    return enabled() and os.getenv("PD_NATIVE_SMS_ISOLATED") == "YES" and os.getenv("PD_NATIVE_SMS_LIVE") == "NO"

def telegram_order(uid, data):
    if not safe():
        return jsonify(error="orders_disabled"), 503
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
    digest = fingerprint((values, json.dumps(data, sort_keys=True, ensure_ascii=False)))
    oid = str(uuid.uuid4())
    qa26 = os.getenv("PD_QA26_ASSIGNMENT") == "1"
    status = "requested"
    import psycopg
    try:
        with psycopg.connect(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"], connect_timeout=4) as db:
            row = db.execute("""INSERT INTO public.pd_dispatch_orders
                (id,source,source_order_id,fingerprint,origin,destination,trip_date,trip_time)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(source,source_order_id) DO NOTHING RETURNING id""",
                (oid,values[0],values[1],digest,*values[2:])).fetchone()
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
