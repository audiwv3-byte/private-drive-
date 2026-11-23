"""PRIVATE DRIVE: synthetic persistent-order restart smoke.

Staging-only. Three separate invocations around a Render Web Service restart:
  prepare  -> prints only a synthetic UUID
  verify ID -> checks the same row exists on a NEW DB connection
  cleanup ID -> deletes only this synthetic test row

No PII, Telegram, payments or production resources. The caller must create
PD_DISPATCH_ORDERS_DATABASE_URL as a Render secret; never print the URL.
"""
import argparse
import os
import sys
import uuid
from urllib.parse import urlparse
from datetime import datetime, timezone
from pd_dispatch_persistent import SCHEMA

PREFIX = "qa-restart-"


def assert_staging_configuration():
    if os.environ.get("PD_DISPATCH_STAGING_ONLY") != "1":
        raise RuntimeError("Refusing non-staging environment")
    dsn = os.environ.get("PD_DISPATCH_ORDERS_DATABASE_URL", "")
    parsed = urlparse(dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError("Expected a private PostgreSQL URL from Render environment")
    # This currently deployed free test DB is named private_drive_test.
    # Prevent accidental writes to another database until explicitly reviewed.
    if parsed.path.lstrip("/") != "private_drive_test":
        raise RuntimeError("Refusing database other than private_drive_test")
    return dsn


def check_id(value):
    try:
        marker = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid synthetic order ID") from exc
    return marker


def run(stage, marker=None):
    import psycopg

    dsn = assert_staging_configuration()
    with psycopg.connect(dsn, connect_timeout=5,
                         options="-c statement_timeout=5000") as db:
        if stage == "prepare":
            db.execute(SCHEMA)
            order_id = str(uuid.uuid4())
            original_id = PREFIX + order_id
            today = datetime.now(timezone.utc).date().isoformat()
            with db.cursor() as cur:
                cur.execute("""INSERT INTO pd_dispatch_orders
                    (id,source,source_order_id,fingerprint,origin,destination,
                     trip_date,trip_time,status)
                    VALUES (%s,'website',%s,'qa-restart-sentinel',
                            'TEST pickup','TEST destination',%s,'12:00','requested')""",
                            (order_id, original_id, today))
            return "PREPARED " + order_id

        marker = check_id(marker)
        original_id = PREFIX + marker
        if stage == "verify":
            row = db.execute("""SELECT source_order_id,status FROM pd_dispatch_orders
                WHERE id=%s AND source='website' AND source_order_id=%s
                AND fingerprint='qa-restart-sentinel'""",
                (marker, original_id)).fetchone()
            if row != (original_id, "requested"):
                raise RuntimeError("Synthetic order not found after restart")
            return "PERSISTED " + marker
        if stage == "cleanup":
            count = db.execute("""DELETE FROM pd_dispatch_orders
                WHERE id=%s AND source='website' AND source_order_id=%s
                AND fingerprint='qa-restart-sentinel'""", (marker, original_id)).rowcount
            if count != 1:
                raise RuntimeError("Synthetic order missing or already deleted")
            return "CLEANED " + marker
    raise ValueError("Unknown stage")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "verify", "cleanup"))
    parser.add_argument("marker", nargs="?")
    args = parser.parse_args()
    if (args.stage == "prepare") == (args.marker is not None):
        parser.error("prepare takes no ID; verify/cleanup require the returned ID")
    print(run(args.stage, args.marker))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No DSNs, connection errors or private credentials in logs.
        print("DATABASE_RESTART_CHECK_FAILED: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
