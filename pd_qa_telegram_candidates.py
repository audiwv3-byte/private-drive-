"""QA-only dispatcher queue for Telegram driver applications."""
import os

from psycopg import Error, connect
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


def database_url():
    if (os.environ.get("PD_DISPATCH_STAGING_ONLY") != "1"
            or os.environ.get("PD_QA_MINIAPP_POSTGRES") != "1"
            or os.environ.get("PD_PAYMENT_MODE") != "disabled"
            or os.environ.get("PD_NATIVE_SMS_LIVE") != "NO"):
        return None

    dsn = os.environ.get("PD_DISPATCH_ORDERS_DATABASE_URL", "")
    try:
        params = conninfo_to_dict(dsn)
    except (Error, ValueError):
        return None
    if (params.get("host"), params.get("port"), params.get("dbname")) != (
        "127.0.0.1", "5432", "private_drive_test"
    ) or "hostaddr" in params or "service" in params:
        return None
    return dsn


def publish(dsn, application):
    with connect(dsn, connect_timeout=3, options="-c statement_timeout=3000") as db:
        db.execute("""
            INSERT INTO public.pd_qa_telegram_candidates
                (telegram_id, name, phone, city, vehicle, vehicle_year, plate, status, updated_at)
            VALUES (%(telegram_id)s, %(name)s, %(phone)s, %(city)s, %(vehicle)s,
                    %(vehicle_year)s, %(plate)s, %(status)s, %(updated_at)s)
            ON CONFLICT (telegram_id) DO UPDATE SET
                name=excluded.name, phone=excluded.phone, city=excluded.city,
                vehicle=excluded.vehicle, vehicle_year=excluded.vehicle_year,
                plate=excluded.plate, status=excluded.status, updated_at=excluded.updated_at
            WHERE pd_qa_telegram_candidates.updated_at <= excluded.updated_at
        """, application)


def recent(dsn):
    with connect(dsn, connect_timeout=3, options="-c statement_timeout=3000", row_factory=dict_row) as db:
        return db.execute("""
            SELECT name, phone, city, vehicle, vehicle_year, plate, status
            FROM public.pd_qa_telegram_candidates ORDER BY updated_at DESC, telegram_id DESC LIMIT 200
        """).fetchall()
