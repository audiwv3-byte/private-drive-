"""QA-only staging readiness: classify staging configuration and schema failures.

The response contains only fixed reason codes, never connection strings or secrets.
"""
import os

REQUIRED = {
    "PD_QA25_WSGI": "1",
    "PD_DISPATCH_STAGING_ONLY": "1",
    "PD_DISPATCH_PERSISTENT_QUEUE": "1",
    "PD_PAYMENT_MODE": "disabled",
    "PD_NATIVE_SMS_ISOLATED": "YES",
    "PD_NATIVE_SMS_LIVE": "NO",
}

# These objects are used by the shared WSGI's Telegram, native and dispatch routes.
BASE_RELATIONS = (
    "public.pd_dispatch_orders",
    "public.pd_native_order_owners",
)
QA26_RELATIONS = (
    "public.pd_telegram_order_owners",
    "public.pd_native_order_assignments",
)

# Read/write privileges are needed by real order endpoints, not just a SELECT 1 ping.
TABLE_PERMISSIONS = (
    ("public.pd_dispatch_orders", "SELECT,INSERT"),
    ("public.pd_native_order_owners", "SELECT,INSERT"),
)
QA26_TABLE_PERMISSIONS = (
    ("public.pd_telegram_order_owners", "SELECT,INSERT"),
)

BASE_FUNCTIONS = ("public.pd_validate_native_session(text,bigint)",)
QA26_FUNCTIONS = (
    "public.pd_pilot_assignment_candidates(bigint)",
    "public.pd_assign_native_order(uuid,text,text,bigint)",
    "public.pd_native_pilot_order_state(text,bigint)",
    "public.pd_native_pilot_trip_action(text,text,text,bigint)",
)
QA27_FUNCTIONS = (
    "public.pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint)",
    "public.pd_qa27_dispatch_gps(uuid,bigint)",
)



def check(*, connect=None, environment=None):
    env = os.environ if environment is None else environment
    if any(env.get(name) != expected for name, expected in REQUIRED.items()):
        return {"ready": False, "reason": "staging_flags_invalid"}
    assignment = env.get("PD_QA26_ASSIGNMENT") == "1"
    gps = env.get("PD_QA27_GPS") == "1"
    if gps and not assignment:
        return {"ready": False, "reason": "staging_flags_invalid"}
    if assignment and env.get("PD_NATIVE_PILOT_ASSIGNMENT") != "1":
        return {"ready": False, "reason": "staging_flags_invalid"}
    url = env.get("PD_DISPATCH_ORDERS_DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        return {"ready": False, "reason": "database_url_invalid"}
    if assignment:
        # Match the assignment API's data-store guard; credentials may differ.
        from pd_native_pilot_assignment import _database_target
        if (_database_target(url) is None
                or _database_target(url) != _database_target(
                    env.get("PD_PILOT_ASSIGNMENT_DATABASE_URL", ""))):
            return {"ready": False, "reason": "assignment_database_mismatch"}
    if connect is None:
        import psycopg
        connect = psycopg.connect
    try:
        with connect(url, connect_timeout=4, options="-c statement_timeout=4000") as db:
            row = db.execute("SELECT 1").fetchone()
            if row != (1,):
                return {"ready": False, "reason": "database_healthcheck_failed"}
            relations = BASE_RELATIONS + (QA26_RELATIONS if assignment else ())
            for relation in relations:
                if db.execute("SELECT to_regclass(%s)", (relation,)).fetchone()[0] is None:
                    return {"ready": False, "reason": "database_schema_missing"}
            functions = (BASE_FUNCTIONS
                         + (QA26_FUNCTIONS if assignment else ())
                         + (QA27_FUNCTIONS if gps else ()))
            for signature in functions:
                if db.execute("SELECT to_regprocedure(%s)", (signature,)).fetchone()[0] is None:
                    return {"ready": False, "reason": "database_schema_missing"}
            permissions = TABLE_PERMISSIONS + (
                QA26_TABLE_PERMISSIONS if assignment else ()
            )
            for relation, access in permissions:
                for privilege in access.split(","):
                    if db.execute(
                        "SELECT has_table_privilege(current_user, %s, %s)",
                        (relation, privilege),
                    ).fetchone() != (True,):
                        return {"ready": False, "reason": "database_permissions_missing"}
            for signature in functions:
                if db.execute(
                    "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
                    (signature,),
                ).fetchone() != (True,):
                    return {"ready": False, "reason": "database_permissions_missing"}
    except Exception:
        return {"ready": False, "reason": "database_unavailable"}
    return {"ready": True, "reason": "ok"}
