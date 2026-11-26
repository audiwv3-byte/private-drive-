"""In-memory pilot presence and server-side assignment for the isolated QA queue."""

from dataclasses import dataclass
import json
import math
import time
from uuid import uuid4

from test_sync_server.pd_demo_server import DB_LOCK, DemoStore, TripError


PILOTS = ("pilot_test", "pilot_test_2")
PILOT = PILOTS[0]
ONLINE_SECONDS = 15
OFFER_SECONDS = 20
_AUTOPILOT_ACTOR = "autopilot_qa"
_DISPATCHER_ACTOR = "dispatcher_test"


@dataclass(frozen=True)
class PilotOffer:
    id: str
    pilot: str
    version: int
    deadline: float


class StagingTripStore(DemoStore):
    def __init__(self, path):
        super().__init__(path)
        self.autopilot = False
        self.pilot_poll = {}
        self.pilot_fixes = {}
        self.last_assignment = {}
        self.offers = {}
        self.offered_pilots = {}
        self.passenger_position = None
        self.last_passenger_fix = float("-inf")
        with DB_LOCK, self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS qa_source_imports (
                source TEXT NOT NULL,
                source_order_id TEXT NOT NULL,
                trip_id TEXT NOT NULL UNIQUE REFERENCES trips(id),
                payload_hash TEXT NOT NULL,
                trip_date TEXT,
                trip_time TEXT,
                PRIMARY KEY(source, source_order_id)
            )""")

    @property
    def last_pilot_poll(self):
        return self.pilot_poll.get(PILOT, float("-inf"))

    def ping_pilot(self, pilot):
        with DB_LOCK:
            self.pilot_poll[pilot] = time.monotonic()
            self.dispatch_waiting()

    def set_pilot_position(self, pilot, position):
        with DB_LOCK:
            self.pilot_fixes[pilot] = (position, time.monotonic())
            self.dispatch_waiting()

    def set_passenger_position(self, position):
        with DB_LOCK:
            self.passenger_position = position
            self.last_passenger_fix = time.monotonic()

    def _current_pilots(self):
        now = time.monotonic()
        busy = {row["pilot"] for row in self.db.execute(
            "SELECT pilot FROM trips WHERE status IN ('assigned','approaching','underway')"
        )}
        for pilot in PILOTS:
            online = now - self.pilot_poll.get(pilot, float("-inf")) < ONLINE_SECONDS
            point, seen = self.pilot_fixes.get(pilot, (None, float("-inf")))
            yield {
                "id": pilot, "online": online, "busy": pilot in busy,
                "position": point if online and now - seen < ONLINE_SECONDS else None,
            }

    def set_autopilot(self, enabled):
        with DB_LOCK:
            self.autopilot = enabled
            if not enabled:
                self.offers.clear()
                self.offered_pilots.clear()
            self.dispatch_waiting()

    def dispatch_waiting(self):
        with DB_LOCK:
            if not self.autopilot:
                return
            now = time.monotonic()
            self.offers = {trip_id: offer for trip_id, offer in self.offers.items()
                           if offer.deadline > now}
            reserved = {offer.pilot for offer in self.offers.values()}
            eligible = [p["id"] for p in self._current_pilots()
                        if p["online"] and not p["busy"] and p["position"] is not None
                        and p["id"] not in reserved]
            eligible.sort(key=lambda pilot: (self.last_assignment.get(pilot, float("-inf")), pilot))
            if not eligible:
                return
            waiting = self.db.execute("""
                SELECT t.id, t.version FROM trips t
                LEFT JOIN qa_source_imports i ON i.trip_id=t.id
                WHERE t.status='requested'
                  AND COALESCE(i.trip_date,'')=''
                  AND COALESCE(i.trip_time,'')=''
                ORDER BY t.created,t.id
            """).fetchall()
            for order in waiting:
                trip_id = order["id"]
                if trip_id in self.offers:
                    continue
                offered = self.offered_pilots.setdefault(trip_id, set())
                pilot = next((candidate for candidate in eligible if candidate not in offered), None)
                if pilot is None:
                    continue
                self.offers[trip_id] = PilotOffer(uuid4().hex, pilot, order["version"], now + OFFER_SECONDS)
                offered.add(pilot)
                eligible.remove(pilot)
                if not eligible:
                    break

    def pilot_offer(self, pilot):
        with DB_LOCK:
            self.dispatch_waiting()
            for trip_id, offer in self.offers.items():
                if offer.pilot == pilot:
                    trip = self._get(trip_id)
                    return {"id": offer.id, "trip_id": trip_id, "origin": trip["origin"],
                            "destination": trip["destination"],
                            "seconds_left": max(0, math.ceil(offer.deadline - time.monotonic()))}
            return None

    def respond_offer(self, trip_id, pilot, offer_id, decision):
        if decision not in ("accept", "decline") or not isinstance(offer_id, str):
            raise TripError("invalid_offer_response")
        with DB_LOCK:
            self.dispatch_waiting()
            offer = self.offers.get(trip_id)
            if not offer or offer.pilot != pilot or offer.id != offer_id:
                raise TripError("offer_unavailable", 409)
            result = None
            if decision == "accept":
                available = any(p["id"] == pilot and p["online"] and not p["busy"]
                                and p["position"] is not None for p in self._current_pilots())
                if not available:
                    del self.offers[trip_id]
                    self.dispatch_waiting()
                    raise TripError("pilot_unavailable", 409)
                result = self.assign(trip_id, pilot, offer.version, _AUTOPILOT_ACTOR)
                self.last_assignment[pilot] = time.monotonic()
                self.offered_pilots.pop(trip_id, None)
            del self.offers[trip_id]
            self.dispatch_waiting()
            return result

    def assign_manually(self, trip_id, pilot, version):
        with DB_LOCK:
            if not any(p["id"] == pilot and not p["busy"] for p in self._current_pilots()):
                raise TripError("pilot_unavailable", 409)
            if any(offer.pilot == pilot and existing != trip_id
                   and offer.deadline > time.monotonic() for existing, offer in self.offers.items()):
                raise TripError("pilot_has_offer", 409)
            trip = self.assign(trip_id, pilot, version, _DISPATCHER_ACTOR)
            self.last_assignment[pilot] = time.monotonic()
            self.offers.pop(trip_id, None)
            self.offered_pilots.pop(trip_id, None)
            return trip

    def update_route(self, trip_id, passenger, data):
        origin, destination, stops = self.route_input(data)
        with DB_LOCK:
            with self.db:
                trip = self._get(trip_id)
                self._allowed(trip, "passenger", passenger)
                if type(data.get("version")) is not int or data["version"] != trip["version"]:
                    raise TripError("version_conflict", 409)
                if trip["status"] not in ("requested", "assigned", "approaching", "underway"):
                    raise TripError("route_closed", 409)
                if trip["status"] == "underway" and origin != trip["origin"]:
                    raise TripError("pickup_already_completed", 409)
                if (origin, destination, stops) == (trip["origin"], trip["destination"], trip["stops"]):
                    return trip
                version = trip["version"] + 1
                self.db.execute("""UPDATE trips SET origin=?, destination=?, stops=?, version=?
                    WHERE id=?""", (origin, destination, json.dumps(stops, ensure_ascii=False),
                                   version, trip_id))
                self._event(trip_id, passenger, trip["status"], "route_updated", version)
            self.offers.pop(trip_id, None)
            self.offered_pilots.pop(trip_id, None)
            self.dispatch_waiting()
            return self._get(trip_id)

    def mobile_events(self, trip_id, role, actor, after):
        events = self.events(trip_id, role, actor, after)
        for event in events:
            if event["actor"] == _AUTOPILOT_ACTOR:
                event["actor"] = _DISPATCHER_ACTOR
        return events

    def snapshot(self):
        with DB_LOCK:
            self.dispatch_waiting()
            now = time.monotonic()
            pilots = list(self._current_pilots())
            for pilot in pilots:
                pilot["has_offer"] = any(offer.pilot == pilot["id"] for offer in self.offers.values())
            trips = self.db.execute("""
                SELECT t.id, t.origin, t.destination, t.stops, t.pilot, t.status,
                       t.paused, t.version, i.source, i.source_order_id,
                       i.trip_date, i.trip_time,
                       EXISTS(SELECT 1 FROM events e WHERE e.trip_id=t.id
                         AND e.actor=? AND e.event='assigned') AS auto_assigned
                FROM trips t LEFT JOIN qa_source_imports i ON i.trip_id=t.id
                ORDER BY t.created DESC LIMIT 50
            """, (_AUTOPILOT_ACTOR,))
            return {
                "autopilot": self.autopilot,
                "pilots": pilots,
                "pilot_online": any(p["online"] for p in pilots),
                "pilot_position": next((p["position"] for p in pilots if p["position"]), None),
                "passenger_position": self.passenger_position
                    if now - self.last_passenger_fix < ONLINE_SECONDS else None,
                "trips": [dict(row, stops=json.loads(row["stops"]),
                               awaiting_response=row["id"] in self.offers) for row in trips],
            }
