"""Loopback-only Mock API for the main Flutter cabinets.

Reuses native OTP/session storage and the existing SQLite trips and chat. The
only accounts are synthetic fixtures. OTP delivery is a private test callback.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from pd_native_auth import issue_code, verify_code
from pd_native_auth_sessions import authenticate_session, issue_session

from pd_demo_server import ApiHandler, ApiServer, DB_LOCK, DemoStore, NEXT, TripError
from test_sync_server.pd_passenger_location import PassengerLocations

PHONES = {
    "+12025550101": "passenger",
    "+12025550102": "pilot",
    "+12025550103": "dispatcher",
    "+12025550104": "passenger",
}
PHOTO = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPYOTME"
    "AAO1Aac26Q9UAAAAAElFTkSuQmCC"
)


def utc_now():
    return datetime.now(timezone.utc)


class CabinetStore(DemoStore):
    def __init__(self, path, *, clock=utc_now):
        super().__init__(path)
        self.clock = clock
        self.pilot_id = None
        self.online = False
        self.gps = None
        self.passenger_locations = PassengerLocations(lambda: self.clock().timestamp())
        self.photo_status = "unverified"
        self.photo_id = None
        with DB_LOCK, self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS cabinet_bookings (
                trip_id TEXT PRIMARY KEY, owner TEXT NOT NULL, client_id TEXT NOT NULL,
                payload TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0,
                arrived_at TEXT, departed_at TEXT, stop_started_at TEXT,
                stop_ms TEXT NOT NULL DEFAULT '[]', UNIQUE(owner, client_id)
            )""")

    def _get(self, trip_id):
        row = super()._get(trip_id)
        extra = self.db.execute(
            "SELECT payload, accepted, arrived_at, departed_at, stop_started_at, stop_ms "
            "FROM cabinet_bookings WHERE trip_id=?", (trip_id,),
        ).fetchone()
        if extra:
            row.update({key: extra[key] for key in extra.keys()
                        if key not in ("payload", "stop_ms")})
            row.update(booking=json.loads(extra["payload"]),
                       accepted=bool(extra["accepted"]),
                       stop_ms=json.loads(extra["stop_ms"]))
        return row

    def create(self, actor, data):
        client_id = data.get("client_id")
        if not isinstance(client_id, str) or not re.fullmatch(r"[a-f0-9]{32}", client_id):
            raise TripError("invalid_client_id")
        try:
            departure = datetime.fromisoformat(data["departure"])
            if departure.tzinfo is None:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise TripError("invalid_departure") from None
        services = data.get("services", [])
        if (not isinstance(services, list) or len(services) > 40 or
                any(not isinstance(s, str) or len(s) > 500 for s in services)):
            raise TripError("invalid_services")
        ride_type = data.get("ride_type", "Трансфер")
        if not isinstance(ride_type, str) or not 1 <= len(ride_type) <= 60:
            raise TripError("invalid_ride_type")
        booking = {"departure": departure.isoformat(), "ride_type": ride_type,
                   "services": services}
        for field in ("round_trip", "advance_booking", "extras_require_quote"):
            value = data.get(field, False)
            if type(value) is not bool:
                raise TripError("invalid_booking")
            booking[field] = value
        for field, limit in (("estimated_fare_eur", 1_000_000),
                             ("estimated_fare_cents", 100_000_000)):
            value = data.get(field)
            if value is not None and (type(value) is not int or not 0 <= value <= limit):
                raise TripError("invalid_booking")
            booking[field] = value
        with DB_LOCK, self.db:
            previous = self.db.execute(
                "SELECT trip_id FROM cabinet_bookings WHERE owner=? AND client_id=?",
                (actor, client_id),
            ).fetchone()
            if previous:
                return self._get(previous["trip_id"])
            trip = self._insert_trip(actor, data)
            self.db.execute(
                "INSERT INTO cabinet_bookings(trip_id,owner,client_id,payload) VALUES(?,?,?,?)",
                (trip["id"], actor, client_id, json.dumps(booking)),
            )
            return self._get(trip["id"])

    def assign_current_pilot(self, trip_id, actor, version):
        with DB_LOCK:
            if not self.online or self.pilot_id is None or self.photo_status != "approved":
                raise TripError("pilot_unavailable", 409)
            if self.db.execute(
                "SELECT 1 FROM trips WHERE pilot=? AND status IN ('assigned','approaching','underway')",
                (self.pilot_id,),
            ).fetchone():
                raise TripError("pilot_busy", 409)
            return super().assign(trip_id, self.pilot_id, version, actor)

    def action(self, trip_id, role, actor, version, action):
        with DB_LOCK, self.db:
            row = self.get(trip_id, role, actor)
            if type(version) is not int or version != row["version"]:
                raise TripError("version_conflict", 409)
            status, paused, pilot = row["status"], row["paused"], row["pilot"]
            accepted = row["accepted"]
            arrived, departed = row["arrived_at"], row["departed_at"]
            stop = row["stop_started_at"]
            waits = row["stop_ms"]
            now = self.clock()
            stamp = now.isoformat()
            if role == "passenger" and action == "cancel" and status in ("requested", "assigned"):
                status, accepted = "cancelled", False
            elif role != "pilot":
                raise TripError("forbidden", 403)
            elif action == "accept" and status == "assigned" and not accepted:
                accepted = True
            elif action == "decline" and status == "assigned" and not accepted:
                status, pilot = "requested", None
            elif action == "advance" and accepted and not paused and status in NEXT:
                if status == "approaching":
                    if not arrived:
                        raise TripError("arrival_required", 409)
                    departed = stamp
                status = NEXT[status]
            elif action == "arrive" and accepted and status == "approaching" and not paused and not arrived:
                arrived = stamp
            elif action == "pause" and accepted and status in ("approaching", "underway") and not paused:
                paused, stop = True, stamp
            elif action == "resume" and accepted and paused and stop:
                waits.append(max(0, int((now - datetime.fromisoformat(stop)).total_seconds() * 1000)))
                paused, stop = False, None
            else:
                raise TripError("invalid_transition", 409)
            self.db.execute(
                "UPDATE trips SET status=?,paused=?,pilot=?,version=? WHERE id=?",
                (status, int(paused), pilot, version + 1, trip_id),
            )
            self.db.execute(
                "UPDATE cabinet_bookings SET accepted=?,arrived_at=?,departed_at=?,stop_started_at=?,stop_ms=? "
                "WHERE trip_id=?", (accepted, arrived, departed, stop, json.dumps(waits), trip_id),
            )
            self._event(trip_id, actor, status, action, version + 1)
            return None if action == "decline" else self._get(trip_id)

    def update_gps(self, actor, body):
        with DB_LOCK:
            if actor != self.pilot_id or self.photo_status != "approved":
                raise TripError("forbidden", 403)
            online = body.get("online")
            lat, lon = body.get("latitude"), body.get("longitude")
            if type(online) is not bool:
                raise TripError("invalid_gps")
            if not online or (lat is None and lon is None):
                self.online, self.gps = online, None
                return
            if (type(lat) not in (int, float) or type(lon) not in (int, float) or
                    not (-90 <= lat <= 90 and -180 <= lon <= 180) or
                    (lat == 0 and lon == 0)):
                raise TripError("invalid_gps")
            try:
                seen = datetime.fromisoformat(body["seen_at"])
                age = (self.clock() - seen).total_seconds()
            except (KeyError, TypeError, ValueError):
                raise TripError("invalid_gps_time") from None
            if not -5 <= age < 90:
                raise TripError("invalid_gps_time")
            self.online = True
            self.gps = {"latitude": lat, "longitude": lon, "seen_at": seen.isoformat()}

    def update_passenger_position(self, trip_id, actor, body):
        with DB_LOCK:
            trip = self.get(trip_id, "passenger", actor)
            try:
                self.passenger_locations.update(trip, body)
            except ValueError as error:
                raise TripError(str(error), 409 if str(error) == "inactive_trip" else 400) from None

    def current_with_gps(self, role, actor):
        with DB_LOCK:
            if role == "dispatcher":
                first = self.db.execute(
                    "SELECT id FROM trips ORDER BY "
                    "CASE status WHEN 'underway' THEN 0 WHEN 'approaching' THEN 0 "
                    "WHEN 'assigned' THEN 0 WHEN 'requested' THEN 1 ELSE 2 END, "
                    "CASE WHEN status='requested' THEN created END ASC, created DESC LIMIT 1"
                ).fetchone()
                trip = self._get(first["id"]) if first else None
            else:
                trip = self.current(role, actor)
            gps = self.gps
            if gps and (self.clock() - datetime.fromisoformat(gps["seen_at"])).total_seconds() >= 90:
                gps = None
            if role != "dispatcher" and not (
                role == "passenger" and trip and trip["status"] in ("assigned", "approaching", "underway")
                and trip["pilot"] == self.pilot_id
            ):
                gps = None
            response = {"trip": trip, "gps": gps}
            if role == "dispatcher":
                active = self.db.execute(
                    "SELECT id, status FROM trips "
                    "WHERE status IN ('requested','assigned','approaching','underway')"
                ).fetchall()
                response["passenger_positions"] = self.passenger_locations.snapshot(active)
            return response


class CabinetHandler(ApiHandler):
    def _auth(self):
        header = self.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        with DB_LOCK, self.server.store.db:
            identity = authenticate_session(self.server.store.db, token)
            role = PHONES.get(identity["destination"]) if identity else None
            if role:
                return role, identity["user_id"]
        raise TripError("unauthorized", 401)

    def _current(self, role, actor):
        return self.server.store.current_with_gps(role, actor)

    def _request(self, method):
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.browser_origin:
            self._reply(403, {"error": "browser_origin_not_allowed"})
            return
        path = urlsplit(self.path)
        try:
            if path.query and not path.path.endswith(("/events", "/messages")):
                raise TripError("invalid_query")
            if method == "POST" and path.path in ("/native-auth/request-code", "/native-auth/verify-code", "/native-auth/qa-session"):
                status, response = self._native_auth(path.path, self._body())
            elif path.path.startswith("/native-identity/"):
                status, response = 200, self._identity(method, path.path)
            elif method == "POST" and path.path == "/v1/gps":
                role, actor = self._auth()
                if role != "pilot":
                    raise TripError("forbidden", 403)
                self.server.store.update_gps(actor, self._body())
                status, response = 200, {"ok": True}
            elif method == "POST" and (match := re.fullmatch(
                r"/v1/trips/([a-f0-9]{32})/passenger-position", path.path,
            )):
                role, actor = self._auth()
                if role != "passenger":
                    raise TripError("forbidden", 403)
                self.server.store.update_passenger_position(match[1], actor, self._body())
                status, response = 200, {"ok": True}
            elif method == "POST" and (match := re.fullmatch(
                r"/v1/trips/([a-f0-9]{32})/(assign|action|cancel)", path.path,
            )):
                role, actor = self._auth()
                trip_id, endpoint = match.groups()
                if role != {"assign": "dispatcher", "action": "pilot", "cancel": "passenger"}[endpoint]:
                    raise TripError("forbidden", 403)
                body = self._body()
                if endpoint == "assign":
                    trip = self.server.store.assign_current_pilot(trip_id, actor, body.get("version"))
                else:
                    if role == "pilot" and self.server.store.photo_status != "approved":
                        raise TripError("forbidden", 403)
                    trip = self.server.store.action(
                        trip_id, role, actor, body.get("version"),
                        "cancel" if endpoint == "cancel" else body.get("action"),
                    )
                status, response = 200, {"trip": trip}
            else:
                return super()._request(method)
            self._reply(status, response)
        except TripError as error:
            self._reply(error.status, {"error": error.code})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _native_auth(self, path, body):
        store = self.server.store
        with DB_LOCK, store.db:
            if path.endswith("/qa-session"):
                if not getattr(self.server, "isolated_qa_auth", False):
                    raise TripError("forbidden", 403)
                requested_role = body.get("role")
                qa_phones = {
                    "passenger": "+12025550101",
                    "pilot": "+12025550102",
                    "dispatcher": "+12025550103",
                }
                target = qa_phones.get(requested_role)
                if target is None:
                    raise TripError("invalid_role", 403)
                session = issue_session(store.db, "phone", target)
                if requested_role == "pilot":
                    store.pilot_id = session["user_id"]
                return 200, {"verified": False, "qa": True, "role": requested_role, **session}
            if path.endswith("/request-code"):
                target = body.get("destination")
                if body.get("channel") != "phone" or not isinstance(target, str) or target not in PHONES:
                    raise TripError("invalid_phone")
                try:
                    challenge, code = issue_code(store.db, self.server.otp_key, "phone", target)
                except ValueError:
                    raise TripError("try_later", 429) from None
                self.server.deliver(target, code)
                return 202, {"challenge_id": challenge, "expires_in": 300, "resend_after": 60}
            verified = verify_code(store.db, self.server.otp_key, body.get("challenge_id"), body.get("code"))
            if verified is None:
                # Commit the failed attempt before responding.
                store.db.commit()
                raise TripError("invalid_or_expired_code", 401)
            channel, target = verified
            session = issue_session(store.db, channel, target)
            role = PHONES[target]
            if role == "pilot":
                store.pilot_id = session["user_id"]
            return 200, {"verified": True, "role": role, **session}

    def _identity(self, method, path):
        role, actor = self._auth()
        route = path.removeprefix("/native-identity/")
        store = self.server.store
        with DB_LOCK:
            if role == "pilot":
                if (method, route) == ("GET", "status"):
                    return {"status": store.photo_status}
                if (method, route) == ("POST", "submit"):
                    if self._body().get("photo") != PHOTO:
                        raise TripError("synthetic_photo_required")
                    store.photo_id, store.photo_status = uuid.uuid4().hex, "pending"
                    return {"status": "pending"}
            if role == "dispatcher":
                if (method, route) == ("GET", "queue"):
                    return {"items": [{"id": store.photo_id, "user_id": store.pilot_id}]
                            if store.photo_status == "pending" else []}
                if store.photo_status == "pending" and store.photo_id is not None:
                    if (method, route) == ("GET", "photo/" + store.photo_id):
                        return {"photo": PHOTO}
                    if (method, route) == ("POST", "decision/" + store.photo_id):
                        decision = self._body().get("decision")
                        if decision not in ("approved", "rejected"):
                            raise TripError("invalid_decision")
                        store.photo_status, store.photo_id = decision, None
                        return {"status": decision}
            raise TripError("forbidden", 403)


def make_mock_server(store, deliver, *, port=0, browser_origin=None, handler=CabinetHandler, isolated_qa_auth=False):
    server = ApiServer(("127.0.0.1", port), store, {},
                       browser_origin=browser_origin, handler=handler)
    server.deliver = deliver
    server.otp_key = secrets.token_bytes(32)
    server.isolated_qa_auth = isolated_qa_auth
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-directory", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=args.test_directory) as state:
        store = CabinetStore(Path(state) / "trips.sqlite")
        def deliver(target, code):
            (args.test_directory / target[1:]).write_text(code)
        with make_mock_server(store, deliver, port=args.port) as server:
            (args.test_directory / "port").write_text(str(server.server_port))
            try:
                server.serve_forever()
            finally:
                store.close()


if __name__ == "__main__":
    main()
