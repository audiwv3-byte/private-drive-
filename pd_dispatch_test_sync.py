"""Expose the isolated mobile QA trip store to the authenticated test dispatcher."""

import hashlib
import hmac
import json
import os
import sqlite3
import re
import secrets
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import jsonify, redirect, render_template, render_template_string, request, url_for

from pd_telegram_test import VALID_ID, verify_init_data
from test_sync_server.pd_demo_server import DB_LOCK, MAX_BODY, DemoStore, TripError


PILOT = "pilot_test"
ROLES = {"passenger": "passenger_test", "pilot": PILOT}
ONLINE_SECONDS = 15
TRIP_ID = re.compile(r"[a-f0-9]{32}")
TELEGRAM_TEST_ORDER = {
    "source": "telegram_miniapp", "source_order_id": "9900000000000000001",
    "from": "Вильнюс, тестовая точка подачи", "to": "Каунас, тестовая точка назначения",
    "trip_date": "2099-01-01", "trip_time": "12:00",
}


def telegram_test_enabled():
    return (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.environ.get("PD_DISPATCH_TEST_SYNC") == "1"
            and bool(VALID_ID.fullmatch(os.environ.get("PD_QA_TELEGRAM_BOT_ID", "")))
            and bool(VALID_ID.fullmatch(os.environ.get("PD_DISPATCH_ADMIN_ID", ""))))


class StagingTripStore(DemoStore):
    last_pilot_poll = float("-inf")
    pilot_position = None
    last_pilot_fix = float("-inf")

    def ping_pilot(self):
        with DB_LOCK:
            self.last_pilot_poll = time.monotonic()

    def set_pilot_position(self, position):
        with DB_LOCK:
            self.pilot_position = position
            self.last_pilot_fix = time.monotonic()

    def snapshot(self):
        with DB_LOCK:
            now = time.monotonic()
            online = now - self.last_pilot_poll < ONLINE_SECONDS
            position = self.pilot_position if online and now - self.last_pilot_fix < ONLINE_SECONDS else None
            trips = self.db.execute("""
                SELECT t.id, t.origin, t.destination, t.pilot, t.status,
                       t.paused, t.version, i.source, i.source_order_id,
                       i.trip_date, i.trip_time
                FROM trips t LEFT JOIN qa_source_imports i ON i.trip_id=t.id
                ORDER BY t.created DESC LIMIT 50
            """)
            return {
                "pilot_online": online,
                "pilot_position": position,
                "trips": [dict(row) for row in trips],
            }


def register(app, authorized, valid_csrf, *, csrf=None):
    directory = TemporaryDirectory(prefix="pd-test-trips-")
    store = StagingTripStore(Path(directory.name) / "trips.sqlite")
    app.extensions["pd_dispatch_test_sync"] = (directory, store)
    with DB_LOCK, store.db:
        store.db.execute("""CREATE TABLE IF NOT EXISTS qa_source_imports (
            source TEXT NOT NULL,
            source_order_id TEXT NOT NULL,
            trip_id TEXT NOT NULL UNIQUE,
            payload_hash TEXT NOT NULL,
            trip_date TEXT,
            trip_time TEXT,
            PRIMARY KEY(source, source_order_id),
            FOREIGN KEY(trip_id) REFERENCES trips(id)
        )""")

    def token(role, day):
        purpose = f"pd-dispatch-staging-mobile-test:v1:{role}:{day}".encode("ascii")
        return hmac.new(app.secret_key.encode(), purpose, hashlib.sha256).hexdigest()

    def identify():
        bearer = request.headers.get("Authorization", "")
        if not re.fullmatch(r"Bearer [a-f0-9]{64}", bearer):
            raise TripError("unauthorized", 401)
        day = int(time.time()) // 86400
        for role, actor in ROLES.items():
            for issued in (day, day - 1):
                if hmac.compare_digest(bearer[7:], token(role, issued)):
                    return role, actor
        raise TripError("unauthorized", 401)

    def reply(data, status=200):
        response = jsonify(data)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        return response

    def payload():
        if request.content_length is None or not 0 < request.content_length <= MAX_BODY:
            raise TripError("invalid_body", 400)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TripError("invalid_body", 400)
        return body

    def cursor():
        values = request.args.getlist("after")
        if not values and not request.args:
            return 0
        if set(request.args) != {"after"} or len(values) != 1 or not re.fullmatch(r"[0-9]{1,10}", values[0]):
            raise TripError("invalid_after")
        return int(values[0])

    def mobile_response(role, actor, path):
        if request.method == "GET" and path == "me":
            return reply({"role": role, "actor": actor, "demo": True})
        if request.method == "GET" and path == "current":
            if role == "pilot":
                store.ping_pilot()
            return reply({"trip": store.current(role, actor)})
        if request.method == "POST" and path == "trips":
            if role != "passenger":
                raise TripError("forbidden", 403)
            return reply({"trip": store.create(actor, payload())}, 201)
        if request.method == "POST" and path == "position":
            if role != "pilot":
                raise TripError("forbidden", 403)
            body = payload()
            if set(body) != {"latitude", "longitude"}:
                raise TripError("invalid_position")
            latitude, longitude = body["latitude"], body["longitude"]
            if latitude is None and longitude is None:
                store.set_pilot_position(None)
            elif (type(latitude) in (int, float) and -90 <= latitude <= 90
                  and type(longitude) in (int, float) and -180 <= longitude <= 180):
                store.set_pilot_position([round(latitude, 5), round(longitude, 5)])
            else:
                raise TripError("invalid_position")
            return reply({"ok": True})
        parts = path.split("/")
        if len(parts) < 2 or parts[0] != "trips" or not TRIP_ID.fullmatch(parts[1]):
            raise TripError("not_found", 404)
        trip_id = parts[1]
        action = parts[2:]
        if request.method == "GET":
            if not action:
                return reply({"trip": store.get(trip_id, role, actor)})
            if action == ["events"]:
                return reply({"events": store.events(trip_id, role, actor, cursor())})
            if action == ["messages"]:
                return reply({"messages": store.messages(trip_id, role, actor, cursor())})
        if request.method == "POST":
            if action == ["messages"]:
                return reply({"message": store.send_message(trip_id, role, actor, payload())}, 201)
            if action == ["action"]:
                if role != "pilot":
                    raise TripError("forbidden", 403)
                body = payload()
                return reply({"trip": store.advance(trip_id, actor, body.get("version"), body.get("action"))})
        raise TripError("not_found", 404)

    @app.route("/v1/<path:path>", methods=["GET", "POST"])
    def pd_test_mobile(path):
        try:
            return mobile_response(*identify(), path)
        except TripError as exc:
            return reply({"error": exc.code}, exc.status)

    # Public-facing staging website intake. This deliberately creates only a
    # synthetic QA trip in the existing dispatcher queue; no live booking,
    # payments, SMS, credentials or production database is involved.
    # A per-IP cap and a one-use browser reference reduce accidental duplicates.
    web_attempts = {}
    web_references = {}

    @app.post("/preview/api/qa-booking")
    def pd_test_website_booking():
        origin = request.headers.get("Origin", "")
        expected_origin = request.host_url.rstrip("/")
        if origin not in (expected_origin, "https://" + request.host):
            return reply({"error": "invalid_origin"}, 403)
        if request.mimetype != "application/json":
            return reply({"error": "invalid_body"}, 400)
        try:
            body = payload()
            if set(body) != {"from", "to", "reference", "source"}:
                raise TripError("invalid_body", 400)
            source = body["source"]
            if source not in ("quick", "detailed"):
                raise TripError("invalid_source", 400)
            reference = body["reference"]
            if not isinstance(reference, str) or not TRIP_ID.fullmatch(reference):
                raise TripError("invalid_reference", 400)
            now = time.monotonic()
            remote = request.remote_addr or "unknown"
            # Test-only memory limiter: max 3 submissions per IP each hour.
            with DB_LOCK:
                recent = [t for t in web_attempts.get(remote, []) if now - t < 3600]
                # The same reference can be retried safely after a lost response.
                if reference in web_references:
                    trip_id = web_references[reference]
                    return reply({"trip": store.get(trip_id, "dispatcher", "dispatcher_test"),
                                  "qa_only": True})
                if len(recent) >= 3:
                    raise TripError("rate_limited", 429)
                web_attempts[remote] = recent + [now]
            actor = "website_qa_" + reference
            trip = store.create(actor, {
                "from": body["from"], "to": body["to"], "payment": "Карта"
            })
            with DB_LOCK:
                web_references[reference] = trip["id"]
            return reply({"trip": trip, "qa_only": True}, 201)
        except TripError as exc:
            return reply({"error": exc.code}, exc.status)

    # Server-only synthetic QA bridge; disabled without a staging-only secret.
    @app.post("/v1/qa-source/import")
    def pd_import_external_qa_order():
        secret = os.environ.get("PD_QA_SOURCE_BRIDGE_SECRET", "")
        if len(secret) < 32 or os.environ.get("PD_DISPATCH_STAGING_ONLY") != "1":
            return reply({"error": "bridge_disabled"}, 503)
        if request.mimetype != "application/json":
            return reply({"error": "invalid_body"}, 400)
        if request.content_length is None or not 0 < request.content_length <= MAX_BODY:
            return reply({"error": "invalid_body"}, 400)
        issued = request.headers.get("X-PD-QA-Timestamp", "")
        mac = request.headers.get("X-PD-QA-Signature", "")
        if not re.fullmatch(r"[0-9]{10,12}", issued) or not re.fullmatch(r"[a-f0-9]{64}", mac):
            return reply({"error": "unauthorized"}, 401)
        if abs(int(time.time()) - int(issued)) > 300:
            return reply({"error": "expired_signature"}, 401)
        raw = request.get_data(cache=True)
        signed = issued.encode("ascii") + b"." + raw
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return reply({"error": "unauthorized"}, 401)
        try:
            data = json.loads(raw)
        except (UnicodeError, ValueError):
            return reply({"error": "invalid_body"}, 400)
        return import_source_order(data)

    def import_source_order(data):
        if not isinstance(data, dict) or set(data) != {
                "source", "source_order_id", "from", "to", "trip_date", "trip_time"}:
            return reply({"error": "invalid_body"}, 400)
        source, original = data["source"], data["source_order_id"]
        if source not in ("telegram_miniapp", "telegram_bot"):
            return reply({"error": "invalid_source"}, 400)
        if not isinstance(original, str) or not re.fullmatch(r"[0-9]{1,20}", original):
            return reply({"error": "invalid_source_order_id"}, 400)
        origin, destination = data["from"], data["to"]
        if (not isinstance(origin, str) or not isinstance(destination, str)
            or not 1 <= len(origin.strip()) <= 200
            or not 1 <= len(destination.strip()) <= 200
            or origin.strip().casefold() == destination.strip().casefold()):
            return reply({"error": "invalid_route"}, 400)
        date, clock = data["trip_date"], data["trip_time"]
        if not isinstance(date, str) or len(date) > 32 or not isinstance(clock, str) or len(clock) > 16:
            return reply({"error": "invalid_departure"}, 400)
        normalized = json.dumps({
            "source": source, "source_order_id": original,
            "from": origin.strip(), "to": destination.strip(),
            "trip_date": date, "trip_time": clock,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        with DB_LOCK:
            row = store.db.execute(
                "SELECT trip_id,payload_hash FROM qa_source_imports WHERE source=? AND source_order_id=?",
                (source, original)).fetchone()
            if row:
                if row["payload_hash"] != digest:
                    return reply({"error": "source_order_conflict"}, 409)
                return reply({"qa_only": True, "replayed": True,
                              "trip": store.get(row["trip_id"], "dispatcher", "dispatcher_test")})
            # Unique internal actor avoids demo passenger single-active-trip limits.
            actor = "source_qa_" + source + "_" + original
            try:
                trip = store.create(actor, {
                    "from": origin.strip(), "to": destination.strip(), "payment": "Карта"
                })
                with store.db:
                    store.db.execute("""INSERT INTO qa_source_imports
                        (source,source_order_id,trip_id,payload_hash,trip_date,trip_time)
                        VALUES (?,?,?,?,?,?)""",
                        (source, original, trip["id"], digest, date, clock))
            except TripError as exc:
                return reply({"error": exc.code}, exc.status)
            except sqlite3.IntegrityError:
                return reply({"error": "source_order_conflict"}, 409)
        return reply({"qa_only": True, "replayed": False, "trip": trip}, 201)

    def telegram_trip():
        with DB_LOCK:
            row = store.db.execute(
                "SELECT trip_id FROM qa_source_imports WHERE source=? AND source_order_id=?",
                (TELEGRAM_TEST_ORDER["source"], TELEGRAM_TEST_ORDER["source_order_id"]),
            ).fetchone()
            return store.get(row["trip_id"], "dispatcher", "dispatcher_test") if row else None

    @app.after_request
    def allow_live_miniapp_for_telegram_test(response):
        if request.path not in ("/preview/telegram-miniapp", "/preview/telegram-miniapp/status"):
            return response
        response.vary.add("Origin")
        origin = "https://wilsonpark.pythonanywhere.com"
        if telegram_test_enabled() and request.headers.get("Origin") == origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            if request.method == "OPTIONS":
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "X-Telegram-Init-Data"
        return response

    @app.get("/preview/telegram-miniapp/client.js")
    def pd_test_telegram_miniapp_script():
        return app.response_class(
            Path(__file__).with_name("pd_telegram_qa.js").read_text(encoding="utf-8"),
            mimetype="text/javascript")

    @app.route("/preview/telegram-miniapp", methods=["GET", "POST"])
    @app.get("/preview/telegram-miniapp/status")
    def pd_test_telegram_miniapp():
        if not telegram_test_enabled():
            return reply({"error": "telegram_qa_disabled"}, 503)
        if request.method == "GET" and not request.path.endswith("/status"):
            return app.make_response((
                render_template("pd_telegram_qa.html"),
                {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; script-src 'self' https://telegram.org; "
                 "connect-src 'self'; form-action 'none'; base-uri 'none'"},
            ))
        try:
            verify_init_data(
                request.headers.get("X-Telegram-Init-Data", ""),
                os.environ["PD_QA_TELEGRAM_BOT_ID"], os.environ["PD_DISPATCH_ADMIN_ID"],
            )
        except PermissionError as error:
            return reply({"error": str(error)}, 403 if str(error) == "forbidden" else 401)
        except (OSError, subprocess.SubprocessError):
            return reply({"error": "telegram_validation_unavailable"}, 503)
        if request.method == "GET":
            trip = telegram_trip()
            return reply({"trip": {"id": trip["id"], "status": trip["status"]} if trip else None})
        return import_source_order(TELEGRAM_TEST_ORDER)

    @app.route("/dispatch/test-miniapp", methods=["GET", "POST"])
    def pd_dispatch_test_miniapp():
        if not telegram_test_enabled() or csrf is None:
            return reply({"error": "telegram_qa_disabled"}, 503)
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        trip = telegram_trip()
        if request.method == "POST":
            if request.content_length is None or request.content_length > MAX_BODY or not valid_csrf():
                return reply({"error": "forbidden"}, 403)
            if not trip or request.form.get("version") != str(trip["version"]):
                return reply({"error": "version_conflict"}, 409)
            try:
                store.assign(trip["id"], PILOT, trip["version"], "dispatcher_test")
            except TripError as error:
                return reply({"error": error.code}, error.status)
            return redirect(url_for("pd_dispatch_test_miniapp"), code=303)
        return render_template("pd_dispatch_test_miniapp.html", trip=trip, csrf=csrf()), {
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        }

    @app.get("/dispatch/test-sync")
    def pd_test_sync_setup():
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        day = int(time.time()) // 86400
        nonce = secrets.token_urlsafe(18)
        page = render_template_string("""<!doctype html><html lang="ru">
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Тестовая связь — PRIVATE DRIVE</title>
<style>
:root{color-scheme:dark}body{max-width:42rem;margin:2rem auto;padding:0 1rem;background:#110f0c;color:#f6efdf;font:1rem/1.5 system-ui}
h1,a{color:#e8c581}label{display:block;margin-top:1rem}input{box-sizing:border-box;width:100%;padding:.6rem}
button{margin-top:.4rem;padding:.55rem .8rem;cursor:pointer}
</style>
<h1>Тестовая связь между устройствами</h1>
<p>После входа в Android QA открой «Тестовая связь с диспетчерской». Вставь скопированный токен в поле «Временный токен».</p>
<label>Адрес сервера<input readonly value="https://private-drive-dispatcher-staging.onrender.com"></label>
<label>Токен пилота<input id="pilot-token" readonly spellcheck="false" value="{{ pilot }}"></label>
<button type="button" data-copy="pilot-token">Скопировать токен пилота</button>
<label>Токен пассажира<input id="passenger-token" readonly spellcheck="false" value="{{ passenger }}"></label>
<button type="button" data-copy="passenger-token">Скопировать токен пассажира</button>
<p id="copy-status" role="status"></p>
<p>Токен состоит из 64 символов. На экране «Тестовый вход» используй пароль QA-сборки.</p>
<p>Используй тестовые адреса. Статус пилота отображается, пока открыт экран тестовой связи. На карте видно последнее местоположение, если пилот включил передачу GPS. Оплата выключена.</p>
<a href="/dispatch/map">Открыть карту диспетчерской</a>
<script nonce="{{ nonce }}">
document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
        const input = document.getElementById(button.dataset.copy);
        const status = document.getElementById('copy-status');
        try {
            await navigator.clipboard.writeText(input.value);
            status.textContent = 'Токен скопирован целиком.';
        } catch (_) {
            input.focus();
            input.select();
            input.setSelectionRange(0, input.value.length);
            status.textContent = 'Токен выделен. Нажми «Копировать».';
        }
    });
});
</script></html>""",
            pilot=token("pilot", day), passenger=token("passenger", day), nonce=nonce)
        return page, {
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; "
                "style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
            ),
        }

    @app.get("/dispatch/test-sync/state")
    def pd_test_sync_state():
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        return reply(store.snapshot())

    @app.post("/dispatch/test-sync/assign")
    def pd_test_sync_assign():
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        try:
            if request.content_length is None or request.content_length > MAX_BODY or not valid_csrf():
                raise TripError("forbidden", 403)
            trip_id = request.form.get("trip_id", "")
            version = request.form.get("version", "")
            if not TRIP_ID.fullmatch(trip_id) or not re.fullmatch(r"[0-9]{1,9}", version):
                raise TripError("invalid_trip")
            return reply({"trip": store.assign(trip_id, PILOT, int(version), "dispatcher_test")})
        except TripError as exc:
            return reply({"error": exc.code}, exc.status)
