"""PRIVATE DRIVE: isolated development-only, single-instance JSON HTTP service.

Start only with PD_DEMO_* variables and a throwaway SQLite path. No app
credentials, payment integrations, Telegram, PythonAnywhere or live orders.
Default bind is loopback; external devices require a separately secured HTTPS
reverse proxy and explicitly configured host.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 8_192
VALID_STATES = {"requested", "assigned", "approaching", "underway", "finished"}
NEXT = {"assigned": "approaching", "approaching": "underway", "underway": "finished"}
DB_LOCK = threading.RLock()


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class TripError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


class DemoStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        with DB_LOCK, self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, pilot TEXT,
                origin TEXT NOT NULL, destination TEXT NOT NULL,
                payment TEXT NOT NULL, status TEXT NOT NULL, paused INTEGER NOT NULL,
                version INTEGER NOT NULL, created TEXT NOT NULL)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL,
                actor TEXT NOT NULL, status TEXT NOT NULL, event TEXT NOT NULL,
                version INTEGER NOT NULL, at TEXT NOT NULL)""")

    def close(self):
        with DB_LOCK:
            self.db.close()

    def _event(self, trip_id, actor, status, action, version):
        self.db.execute("INSERT INTO events(trip_id,actor,status,event,version,at) "
                        "VALUES(?,?,?,?,?,?)",
                        (trip_id, actor, status, action, version, datetime.now(timezone.utc).isoformat()))

    def _get(self, trip_id):
        row = self.db.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
        if row is None:
            raise TripError("not_found", 404)
        return dict(row)

    def _allowed(self, row, role, actor):
        if role == "passenger" and row["owner"] != actor:
            raise TripError("not_found", 404)
        if role == "pilot" and row["pilot"] != actor:
            raise TripError("not_found", 404)

    def create(self, actor, data):
        origin, destination = data.get("from"), data.get("to")
        payment = data.get("payment", "Карта")
        if not isinstance(origin, str) or not isinstance(destination, str):
            raise TripError("invalid_route")
        origin, destination = origin.strip(), destination.strip()
        if not 1 <= len(origin) <= 200 or not 1 <= len(destination) <= 200 or origin.casefold() == destination.casefold():
            raise TripError("invalid_route")
        if payment not in ("Карта", "PayPal", "Банковский перевод", "Криптовалюта"):
            raise TripError("invalid_payment")
        with DB_LOCK, self.db:
            active = self.db.execute("SELECT id FROM trips WHERE owner=? AND status!='finished'", (actor,)).fetchone()
            if active:
                raise TripError("active_trip_exists", 409)
            trip_id = uuid.uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute("INSERT INTO trips VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (trip_id, actor, None, origin, destination, payment, "requested", 0, 1, now))
            self._event(trip_id, actor, "requested", "created", 1)
            return self._get(trip_id)

    def get(self, trip_id, role, actor):
        with DB_LOCK:
            row = self._get(trip_id)
            self._allowed(row, role, actor)
            return row

    def current(self, role, actor):
        with DB_LOCK:
            if role == "passenger":
                row = self.db.execute("SELECT id FROM trips WHERE owner=? ORDER BY created DESC LIMIT 1",
                                      (actor,)).fetchone()
            elif role == "pilot":
                row = self.db.execute("SELECT id FROM trips WHERE pilot=? ORDER BY created DESC LIMIT 1",
                                      (actor,)).fetchone()
            else:
                row = self.db.execute("SELECT id FROM trips ORDER BY created DESC LIMIT 1").fetchone()
            return self._get(row["id"]) if row is not None else None

    def assign(self, trip_id, pilot, version, actor):
        if not isinstance(pilot, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", pilot):
            raise TripError("invalid_pilot")
        return self._transition(trip_id, "dispatcher", actor, version, "assigned", "assigned", pilot=pilot)

    def advance(self, trip_id, actor, version, action):
        if action not in ("advance", "pause", "resume"):
            raise TripError("invalid_action")
        return self._transition(trip_id, "pilot", actor, version, None, action)

    def _transition(self, trip_id, role, actor, version, target, action, pilot=None):
        if type(version) is not int or version < 1:
            raise TripError("invalid_version")
        with DB_LOCK, self.db:
            row = self._get(trip_id)
            self._allowed(row, role, actor)
            if row["version"] != version:
                raise TripError("version_conflict", 409)
            status, paused = row["status"], bool(row["paused"])
            if role == "dispatcher":
                if status != "requested":
                    raise TripError("invalid_transition", 409)
                status = "assigned"
            else:
                if action == "advance":
                    if paused or status not in NEXT:
                        raise TripError("invalid_transition", 409)
                    status = NEXT[status]
                elif action == "pause":
                    if paused or status not in ("approaching", "underway"):
                        raise TripError("invalid_transition", 409)
                    paused = True
                else:
                    if not paused or status not in ("approaching", "underway"):
                        raise TripError("invalid_transition", 409)
                    paused = False
            self.db.execute("UPDATE trips SET pilot=?, status=?, paused=?, version=? WHERE id=?",
                            (pilot if pilot is not None else row["pilot"],
                             status, int(paused), version + 1, trip_id))
            self._event(trip_id, actor, status, action, version + 1)
            return self._get(trip_id)

    def events(self, trip_id, role, actor, after):
        if not 0 <= after <= 2_147_483_647:
            raise TripError("invalid_after")
        with DB_LOCK:
            self._allowed(self._get(trip_id), role, actor)
            return [dict(row) for row in self.db.execute(
                "SELECT seq, trip_id, actor, status, event, version, at "
                "FROM events WHERE trip_id=? AND seq>? ORDER BY seq LIMIT 100",
                (trip_id, after))]


class ApiServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, store, credentials):
        self.store, self.credentials = store, credentials
        super().__init__(address, ApiHandler)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "PD-Demo/1"
    sys_version = ""

    def log_message(self, format, *args):
        pass  # never log bearer credentials or passenger addresses

    def _reply(self, status, obj):
        data = json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise TripError("unauthorized", 401)
        raw = header[7:].strip()
        if len(raw) > 200:
            raise TripError("unauthorized", 401)
        fingerprint = hashlib.sha256(raw.encode()).digest()
        for expected, principal in self.server.credentials.items():
            if hmac.compare_digest(fingerprint, expected):
                return principal
        raise TripError("unauthorized", 401)

    def _body(self):
        length = self.headers.get("Content-Length", "")
        if not length.isdecimal() or int(length) > MAX_BODY:
            raise TripError("invalid_body")
        try:
            obj = json.loads(self.rfile.read(int(length)))
        except (ValueError, UnicodeError):
            raise TripError("invalid_json")
        if not isinstance(obj, dict):
            raise TripError("invalid_body")
        return obj

    def _request(self, method):
        try:
            if self.headers.get("Origin"):
                raise TripError("browser_origin_not_allowed", 403)
            role, actor = self._auth()
            path = urlsplit(self.path)
            if path.query and not (method == "GET" and path.path.endswith("/events")):
                raise TripError("invalid_query")
            parts = path.path.strip("/").split("/")
            if method == "GET" and parts == ["v1", "me"]:
                self._reply(200, {"role": role, "actor": actor, "demo": True})
                return
            if method == "GET" and parts == ["v1", "current"]:
                self._reply(200, {"trip": self.server.store.current(role, actor)})
                return
            if method == "POST" and parts == ["v1", "trips"]:
                if role != "passenger":
                    raise TripError("forbidden", 403)
                self._reply(201, {"trip": self.server.store.create(actor, self._body())})
                return
            if len(parts) >= 3 and parts[:2] == ["v1", "trips"] and re.fullmatch(r"[a-f0-9]{32}", parts[2]):
                trip_id = parts[2]
                if method == "GET" and len(parts) == 3:
                    self._reply(200, {"trip": self.server.store.get(trip_id, role, actor)})
                    return
                if method == "GET" and len(parts) == 4 and parts[3] == "events":
                    from urllib.parse import parse_qs
                    parsed = parse_qs(path.query)
                    if set(parsed) - {"after"} or any(len(v) != 1 for v in parsed.values()):
                        raise TripError("invalid_after")
                    try:
                        after = int(parsed.get("after", ["0"])[0])
                    except ValueError:
                        raise TripError("invalid_after")
                    self._reply(200, {"events": self.server.store.events(trip_id, role, actor, after)})
                    return
                if method == "POST" and len(parts) == 4 and parts[3] == "assign":
                    if role != "dispatcher":
                        raise TripError("forbidden", 403)
                    body = self._body()
                    self._reply(200, {"trip": self.server.store.assign(trip_id, body.get("pilot"), body.get("version"), actor)})
                    return
                if method == "POST" and len(parts) == 4 and parts[3] == "action":
                    if role != "pilot":
                        raise TripError("forbidden", 403)
                    body = self._body()
                    self._reply(200, {"trip": self.server.store.advance(trip_id, actor, body.get("version"), body.get("action"))})
                    return
            raise TripError("not_found", 404)
        except TripError as exc:
            self._reply(exc.status, {"error": exc.code})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._request("GET")

    def do_POST(self):
        self._request("POST")


def demo_credentials():
    result = {}
    for role in ("passenger", "pilot", "dispatcher"):
        token = os.environ.get(f"PD_DEMO_{role.upper()}_TOKEN", "")
        if len(token) < 32 or token.strip() != token:
            raise RuntimeError("All PD_DEMO_*_TOKEN must be 32+ characters")
        fingerprint = hashlib.sha256(token.encode()).digest()
        if fingerprint in result:
            raise RuntimeError("Demo tokens must differ")
        # one synthetic actor per role; no production identity support
        result[fingerprint] = (role, role + "_test")
    return result


def serve():
    if os.environ.get("PD_DEMO_ISOLATED") != "YES":
        raise RuntimeError("PD_DEMO_ISOLATED=YES required")
    host = os.environ.get("PD_DEMO_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "::1"):
        raise RuntimeError("Only loopback bind allowed: HTTPS reverse proxy must be separate")
    port = int(os.environ.get("PD_DEMO_PORT", "8765"))
    path = os.environ.get("PD_DEMO_DB", "")
    if not path or path == ":memory:":
        raise RuntimeError("Explicit throwaway PD_DEMO_DB file path required")
    store = DemoStore(path)
    server = ApiServer((host, port), store, demo_credentials())
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    serve()
