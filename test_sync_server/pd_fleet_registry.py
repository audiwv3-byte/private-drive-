"""Isolated PRIVATE DRIVE pilot registry, using *synthetic* identities and GPS.

No HTTP handlers, production tokens, SMS, live GPS, payments or notifications.
This module records pilot eligibility; an authenticated routing/dispatch layer
must validate the principal and supply verified road ETAs. It deliberately
does not grant access based on a role sent in a mobile request.
"""
from __future__ import annotations

import math
import sqlite3
import time

try:
    from .pd_auto_dispatch import DispatchError, IsolatedDispatch
except ImportError:
    from pd_auto_dispatch import DispatchError, IsolatedDispatch

MAX_GPS_AGE_SECONDS = 90
MAX_ROAD_ETA_SECONDS = 24 * 3600


class IsolatedFleetRegistry:
    """Scoped synthetic registry; dedicated SQLite DB path, no server wiring."""

    def __init__(self, database_path, *, clock=None):
        self.database_path = str(database_path)
        self.clock = clock or time.time
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS fleet_identities (
                    user_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('pilot','dispatcher','passenger')),
                    verified INTEGER NOT NULL CHECK(verified IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS fleet_pilots (
                    user_id TEXT PRIMARY KEY REFERENCES fleet_identities(user_id),
                    approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)),
                    online INTEGER NOT NULL DEFAULT 0 CHECK(online IN (0,1)),
                    vehicle_ready INTEGER NOT NULL DEFAULT 0 CHECK(vehicle_ready IN (0,1)),
                    busy INTEGER NOT NULL DEFAULT 0 CHECK(busy IN (0,1)),
                    latitude REAL,
                    longitude REAL,
                    gps_at REAL,
                    CHECK(latitude IS NULL OR (latitude >= -90 AND latitude <= 90)),
                    CHECK(longitude IS NULL OR (longitude >= -180 AND longitude <= 180))
                );
                CREATE INDEX IF NOT EXISTS idx_fleet_availability
                    ON fleet_pilots(approved,online,vehicle_ready,busy,gps_at);
            """)

    def _db(self):
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _id(user_id):
        return IsolatedDispatch._id(user_id)

    def seed_synthetic_identity(self, user_id, role, *, verified=True):
        """Fixture only: caller is trusted setup, NEVER a public API endpoint."""
        user_id = self._id(user_id)
        if role not in ("pilot", "dispatcher", "passenger") or type(verified) is not bool:
            raise DispatchError("invalid_fixture")
        with self._db() as conn:
            conn.execute("INSERT INTO fleet_identities VALUES (?,?,?)",
                         (user_id, role, int(verified)))
            if role == "pilot":
                conn.execute("INSERT INTO fleet_pilots(user_id) VALUES (?)", (user_id,))

    @staticmethod
    def _authorize(conn, principal, role):
        row = conn.execute("SELECT role,verified FROM fleet_identities WHERE user_id=?",
                           (principal,)).fetchone()
        if row is None or row["role"] != role or not row["verified"]:
            raise DispatchError("forbidden")

    def set_approval(self, pilot_id, *, authenticated_dispatcher, approved):
        """Trusted dispatcher approves/revokes a synthetic pilot."""
        pilot_id = self._id(pilot_id)
        authenticated_dispatcher = self._id(authenticated_dispatcher)
        if type(approved) is not bool:
            raise DispatchError("invalid_action")
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._authorize(conn, authenticated_dispatcher, "dispatcher")
            self._authorize(conn, pilot_id, "pilot")
            conn.execute("UPDATE fleet_pilots SET approved=? WHERE user_id=?",
                         (int(approved), pilot_id))

    def update_presence(self, *, authenticated_pilot, online=None,
                        vehicle_ready=None, busy=None, gps=None):
        """Only this pilot can publish synthetic presence; no cross-user write."""
        authenticated_pilot = self._id(authenticated_pilot)
        updates = {}
        for field, value in (("online", online), ("vehicle_ready", vehicle_ready),
                             ("busy", busy)):
            if value is not None:
                if type(value) is not bool:
                    raise DispatchError("invalid_presence")
                updates[field] = int(value)
        if gps is not None:
            if (not isinstance(gps, (tuple, list)) or len(gps) != 2 or
                any(type(n) not in (int, float) or not math.isfinite(n)
                    for n in gps)):
                raise DispatchError("invalid_gps")
            lat, lon = gps
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise DispatchError("invalid_gps")
            updates.update(latitude=float(lat), longitude=float(lon),
                           gps_at=float(self.clock()))
        if not updates:
            raise DispatchError("no_changes")
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._authorize(conn, authenticated_pilot, "pilot")
            fields = ", ".join(f"{field}=?" for field in updates)
            conn.execute(f"UPDATE fleet_pilots SET {fields} WHERE user_id=?",
                         (*updates.values(), authenticated_pilot))

    @staticmethod
    def _eligible(row, now):
        return (bool(row["approved"]) and bool(row["online"]) and
                bool(row["vehicle_ready"]) and not bool(row["busy"]) and
                row["gps_at"] is not None and 0 <= now - row["gps_at"] <
                MAX_GPS_AGE_SECONDS and
                row["latitude"] is not None and row["longitude"] is not None)

    def eligible_by_road_eta(self, *, authenticated_dispatcher, road_etas):
        """Return eligible pilots sorted by *trusted route ETA*, never straight-line.

        road_etas must come from the authorized server's routing provider.
        Never pass a passenger or pilot supplied mapping here.
        """
        authenticated_dispatcher = self._id(authenticated_dispatcher)
        if not isinstance(road_etas, dict):
            raise DispatchError("invalid_etas")
        validated = {}
        for pilot_id, eta in road_etas.items():
            self._id(pilot_id)
            if type(eta) not in (int, float) or not math.isfinite(eta) or not (
                    0 <= eta <= MAX_ROAD_ETA_SECONDS):
                raise DispatchError("invalid_eta")
            validated[pilot_id] = float(eta)
        with self._db() as conn:
            self._authorize(conn, authenticated_dispatcher, "dispatcher")
            now = self.clock()
            eligible = []
            for pilot_id, eta in validated.items():
                row = conn.execute("""SELECT f.*,i.verified,i.role
                    FROM fleet_pilots f JOIN fleet_identities i
                    ON i.user_id=f.user_id WHERE f.user_id=?""",
                    (pilot_id,)).fetchone()
                if (row is not None and row["verified"] and row["role"] == "pilot"
                        and self._eligible(row, now)):
                    eligible.append((pilot_id, eta))
            eligible.sort(key=lambda item: (item[1], item[0]))
            return eligible

    def offer_nearest_synthetic(self, order_id, *, authenticated_dispatcher,
                                trusted_road_etas):
        """Stage-only bridge into isolated 3-pilot/20-second offer engine.

        This is NOT a public endpoint. Revalidation under the acceptance
        transaction is a required next stage before any real activation.
        """
        candidates = self.eligible_by_road_eta(
            authenticated_dispatcher=authenticated_dispatcher,
            road_etas=trusted_road_etas)
        engine = IsolatedDispatch(self.database_path, clock=self.clock)
        return engine.offer_nearest(order_id, candidates, actor_role="dispatcher")

    def snapshot_pilot(self, pilot_id, *, authenticated_dispatcher):
        pilot_id = self._id(pilot_id)
        with self._db() as conn:
            self._authorize(conn, self._id(authenticated_dispatcher), "dispatcher")
            row = conn.execute("SELECT * FROM fleet_pilots WHERE user_id=?",
                               (pilot_id,)).fetchone()
            return dict(row) if row else None
