"""Expose the isolated mobile QA trip store to the authenticated test dispatcher."""

import hashlib
import hmac
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import jsonify, redirect, render_template_string, request, url_for

from test_sync_server.pd_demo_server import DB_LOCK, MAX_BODY, DemoStore, TripError


PILOT = "pilot_test"
ROLES = {"passenger": "passenger_test", "pilot": PILOT}
ONLINE_SECONDS = 15
TRIP_ID = re.compile(r"[a-f0-9]{32}")


class StagingTripStore(DemoStore):
    last_pilot_poll = float("-inf")

    def ping_pilot(self):
        with DB_LOCK:
            self.last_pilot_poll = time.monotonic()

    def snapshot(self):
        with DB_LOCK:
            trips = self.db.execute("""
                SELECT id, origin, destination, pilot, status, paused, version
                FROM trips ORDER BY created DESC LIMIT 50
            """)
            return {
                "pilot_online": time.monotonic() - self.last_pilot_poll < ONLINE_SECONDS,
                "trips": [dict(row) for row in trips],
            }


def register(app, authorized, valid_csrf):
    directory = TemporaryDirectory(prefix="pd-test-trips-")
    store = StagingTripStore(Path(directory.name) / "trips.sqlite")
    app.extensions["pd_dispatch_test_sync"] = (directory, store)

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

    @app.get("/dispatch/test-sync")
    def pd_test_sync_setup():
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        day = int(time.time()) // 86400
        page = render_template_string("""<!doctype html><html lang="ru">
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Тестовая связь — PRIVATE DRIVE</title>
<style>
:root{color-scheme:dark}body{max-width:42rem;margin:2rem auto;padding:0 1rem;background:#110f0c;color:#f6efdf;font:1rem/1.5 system-ui}
h1,a{color:#e8c581}label{display:block;margin-top:1rem}input{box-sizing:border-box;width:100%;padding:.6rem}
</style>
<h1>Тестовая связь между устройствами</h1>
<p>В приложении открой «Тестовая связь между устройствами». Укажи адрес и токен своей роли.</p>
<label>Адрес сервера<input readonly value="https://private-drive-dispatcher-staging.onrender.com"></label>
<label>Токен пилота<input readonly value="{{ pilot }}"></label>
<label>Токен пассажира<input readonly value="{{ passenger }}"></label>
<p>Используй тестовые адреса. Статус пилота отображается, пока открыт экран тестовой связи. GPS и оплата в этом тесте выключены.</p>
<a href="/dispatch/map">Открыть карту диспетчерской</a></html>""",
            pilot=token("pilot", day), passenger=token("passenger", day))
        return page, {
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
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
