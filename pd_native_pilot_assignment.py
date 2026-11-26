"""Explicit isolated pilot assignment; no GPS, SMS or payment services."""
from contextlib import contextmanager
import json
import os
import re
import time

from pd_native_auth_postgres_session_lifecycle import _digest


def assignment_enabled():
    """Common hard gate. Both services must use the same isolated orders DB."""
    return (
        os.getenv("PD_DISPATCH_STAGING_ONLY") == "1"
        and os.getenv("PD_NATIVE_PILOT_ASSIGNMENT") == "1"
        and os.getenv("PD_DISPATCH_PERSISTENT_QUEUE") == "1"
        and os.getenv("PD_PAYMENT_MODE") == "disabled"
        and os.getenv("PD_DISPATCH_ORDERS_DATABASE_URL", "").startswith(
            ("postgres://", "postgresql://")
        )
    )


def _database_target(url):
    from psycopg.conninfo import conninfo_to_dict

    try:
        fields = conninfo_to_dict(url)
        if any(key in fields for key in ("service", "hostaddr")):
            return None
        host, database = fields.get("host", ""), fields.get("dbname")
        if not host or "," in host or database != "private_drive_test":
            return None
        return host, fields.get("port", "5432"), database
    except Exception:
        return None


def dispatcher_assignment_enabled():
    if not assignment_enabled():
        return False
    reader = _database_target(os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"])
    writer = _database_target(os.getenv("PD_PILOT_ASSIGNMENT_DATABASE_URL", ""))
    return reader is not None and reader == writer


@contextmanager
def _connect(url):
    import psycopg

    with psycopg.connect(url, connect_timeout=4, options="-c statement_timeout=4000") as database:
        if database.execute("SELECT current_database()").fetchone()[0] != "private_drive_test":
            raise RuntimeError("wrong_database")
        yield database


def register_dispatch_assignment(app, authorized, valid_csrf, admin_id, *, clock=time.time):
    from flask import jsonify, request

    def reply(data, code=200):
        response = jsonify(data)
        response.status_code = code
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/dispatch/orders/eligible-pilots")
    def dispatch_eligible_pilots():
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        if not dispatcher_assignment_enabled():
            return reply({"error": "assignment_disabled"}, 503)
        try:
            with _connect(os.environ["PD_PILOT_ASSIGNMENT_DATABASE_URL"]) as db:
                rows = db.execute(
                    "SELECT pilot_user_id FROM public.pd_pilot_assignment_candidates(%s)",
                    (int(clock()),),
                ).fetchall()
            return reply({"pilots": [{"id": row[0]} for row in rows]})
        except Exception as exc:
            app.logger.warning("Pilot list unavailable (%s)", type(exc).__name__)
            return reply({"error": "storage_unavailable"}, 503)

    @app.post("/dispatch/orders/<uuid:order_id>/assign")
    def dispatch_assign_order(order_id):
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        if not dispatcher_assignment_enabled():
            return reply({"error": "assignment_disabled"}, 503)
        if (request.mimetype != "application/x-www-form-urlencoded"
                or request.content_length is None or not 0 < request.content_length <= 1024):
            return reply({"error": "invalid_body"}, 400)
        if not valid_csrf():
            return reply({"error": "csrf_required"}, 403)
        if set(request.form) != {"csrf", "pilot_id"} or any(
            len(request.form.getlist(key)) != 1 for key in request.form
        ):
            return reply({"error": "invalid_request"}, 400)
        pilot_id = request.form.get("pilot_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", pilot_id):
            return reply({"error": "invalid_pilot"}, 400)
        try:
            with _connect(os.environ["PD_PILOT_ASSIGNMENT_DATABASE_URL"]) as db:
                outcome, status = db.execute(
                    "SELECT * FROM public.pd_assign_native_order(%s,%s,%s,%s)",
                    (order_id, pilot_id, str(admin_id() if callable(admin_id) else admin_id), int(clock())),
                ).fetchone()
            if outcome in {"assigned", "already_assigned"}:
                return reply({"order_id": str(order_id), "status": status,
                              "changed": outcome == "assigned"})
            errors = {"order_not_found": 404, "assignment_conflict": 409,
                      "pilot_not_eligible": 409, "invalid_dispatcher": 403}
            if outcome in errors:
                return reply({"error": outcome}, errors[outcome])
            return reply({"error": "assignment_unavailable"}, 503)
        except Exception as exc:
            app.logger.warning("Pilot assignment unavailable (%s)", type(exc).__name__)
            return reply({"error": "storage_unavailable"}, 503)


def _pilot_line_database(auth_database):
    """Use the dedicated login only on the isolated auth service's own staging DB."""
    from psycopg.conninfo import conninfo_to_dict

    url = os.getenv("PD_NATIVE_PILOT_LINE_DATABASE_URL", "").rstrip("\r\n")
    if (not url or os.getenv("PD_NATIVE_SMS_ISOLATED") != "YES"
            or os.getenv("PD_DISPATCH_STAGING_ONLY") != "1"
            or os.getenv("PD_PAYMENT_MODE") != "disabled"):
        return None
    auth = _database_target(auth_database)
    line = _database_target(url)
    if not auth or not line or auth[1:] != line[1:]:
        return None
    hosts = {"dpg-dc00pubm8hqs7397rblg-a",
             "dpg-dc00pubm8hqs7397rblg-a.frankfurt-postgres.render.com"}
    if auth[0] not in hosts or line[0] not in hosts:
        return None
    fields = conninfo_to_dict(url)
    if fields.get("user") == "pd_staging_pilot_line" and fields.get("sslmode") == "require":
        return url
    return None


def make_native_pilot_orders_app(next_app, database_url, *, clock=time.time):
    def app(environ, start_response):
        path = environ.get("PATH_INFO")
        if path not in ("/native-pilot-orders", "/native-pilot-availability"):
            return next_app(environ, start_response)

        def reply(status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            start_response(
                status,
                [("Content-Type", "application/json; charset=utf-8"),
                 ("Cache-Control", "private, no-store"),
                 ("X-Content-Type-Options", "nosniff"),
                 ("Content-Length", str(len(body)))],
            )
            return [body]

        line_db = None
        if path == "/native-pilot-availability":
            line_db = _pilot_line_database(database_url)
        if not line_db and (not assignment_enabled() or os.getenv("PD_NATIVE_SMS_ISOLATED") != "YES"
                or os.getenv("PD_DISPATCH_ORDERS_DATABASE_URL") != database_url
                or _database_target(database_url) is None):
            return reply("503 Service Unavailable", {"error": "assignment_disabled"})
        method = environ.get("REQUEST_METHOD")
        if method not in ("GET", "PATCH"):
            return reply("405 Method Not Allowed", {"error": "method_not_allowed"})
        auth = environ.get("HTTP_AUTHORIZATION", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        digest = _digest(token)
        if not digest or any(c.isspace() for c in token):
            return reply("401 Unauthorized", {"error": "invalid_session"})
        try:
            if path == "/native-pilot-availability":
                requested = None
                if method == "PATCH":
                    try:
                        length = int(environ.get("CONTENT_LENGTH", "0"))
                        if not 0 < length <= 128 or environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                            raise ValueError()
                        payload = json.loads(environ["wsgi.input"].read(length))
                        if not isinstance(payload, dict) or set(payload) != {"online"} or type(payload["online"]) is not bool:
                            raise ValueError()
                        requested = payload["online"]
                    except (ValueError, TypeError, KeyError, AttributeError):
                        return reply("400 Bad Request", {"error": "invalid_availability"})
                with _connect(line_db or database_url) as db:
                    result = db.execute(
                        "SELECT public.pd_native_pilot_availability_state(%s,%s,%s)",
                        (digest, int(clock()), requested),
                    ).fetchone()[0]
                if not isinstance(result, dict):
                    return reply("503 Service Unavailable", {"error": "storage_unavailable"})
                if "error" in result:
                    status = ("401 Unauthorized" if result["error"] == "invalid_session"
                              else "403 Forbidden" if result["error"] in (
                                  "pilot_required", "identity_approval_required")
                              else "503 Service Unavailable")
                    return reply(status, result)
                if result.get("payment_mode") != "disabled" or type(result.get("online")) is not bool:
                    return reply("503 Service Unavailable", {"error": "unsafe_availability"})
                return reply("200 OK", result)
            if method == "PATCH":
                try:
                    size = int(environ.get("CONTENT_LENGTH", "0"))
                    if not 0 < size <= 512 or environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                        raise ValueError()
                    payload = json.loads(environ["wsgi.input"].read(size))
                    if not isinstance(payload, dict) or set(payload) != {"order_id", "action"}:
                        raise ValueError()
                    from uuid import UUID
                    order_id = str(UUID(payload["order_id"]))
                    action = payload["action"]
                    if action not in {"approach", "start", "stop_start", "stop_end", "finish"}:
                        raise ValueError()
                except (ValueError, TypeError, KeyError, AttributeError):
                    return reply("400 Bad Request", {"error": "invalid_trip_action"})
                with _connect(database_url) as db:
                    result = db.execute(
                        "SELECT public.pd_native_pilot_trip_action(%s,%s,%s,%s)",
                        (digest, order_id, action, int(clock())),
                    ).fetchone()[0]
                if not isinstance(result, dict):
                    return reply("503 Service Unavailable", {"error": "storage_unavailable"})
                error = result.get("error")
                if error:
                    code = {"invalid_session": "401 Unauthorized",
                            "pilot_required": "403 Forbidden",
                            "order_not_found": "404 Not Found",
                            "invalid_action": "400 Bad Request",
                            "invalid_transition": "409 Conflict"}.get(error, "503 Service Unavailable")
                    return reply(code, {"error": error})
                if result.get("payment_mode") != "disabled" or result.get("status") not in (
                    "approaching", "underway", "finished"):
                    return reply("503 Service Unavailable", {"error": "unsafe_state"})
                return reply("200 OK", result)
            with _connect(database_url) as db:
                result = db.execute(
                    "SELECT public.pd_native_pilot_order_state(%s,%s)",
                    (digest, int(clock())),
                ).fetchone()[0]
            if not isinstance(result, dict):
                return reply("503 Service Unavailable", {"error": "storage_unavailable"})
            if result.get("error") == "invalid_session":
                return reply("401 Unauthorized", result)
            if result.get("error") in {"pilot_required", "identity_approval_required"}:
                return reply("403 Forbidden", result)
            if result.get("payment_mode") != "disabled" or not isinstance(result.get("orders"), list):
                return reply("503 Service Unavailable", {"error": "storage_unavailable"})
            return reply("200 OK", result)
        except Exception:
            return reply("503 Service Unavailable", {"error": "storage_unavailable"})

    return app
