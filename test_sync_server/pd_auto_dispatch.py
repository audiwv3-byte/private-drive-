"""PRIVATE DRIVE isolated dispatch engine: fake trips, fake pilots, no network.

This is NOT wired to production, Flutter or Render. The caller must use a
server-verified identity, GPS freshness, availability and OSRM route ETAs.
Do not trust client-supplied pilot IDs or distances for authorization.
"""
import sqlite3
import time

BATCH_SIZE = 3
OFFER_SECONDS = 20


class DispatchError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class IsolatedDispatch:
    """SQLite single-winner test engine. Every call has its own transaction."""

    def __init__(self, database_path, *, clock=None):
        self.database_path = str(database_path)
        self.clock = clock or time.time
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS dispatch_orders (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN
                        ('requested','offered','assigned','cancelled')),
                    winner TEXT,
                    round_no INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS dispatch_offers (
                    order_id TEXT NOT NULL REFERENCES dispatch_orders(id),
                    pilot_id TEXT NOT NULL,
                    round_no INTEGER NOT NULL,
                    deadline REAL NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('pending','accepted','declined','expired','lost')),
                    PRIMARY KEY (order_id,pilot_id,round_no)
                );
                CREATE TABLE IF NOT EXISTS dispatch_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    pilot_id TEXT,
                    event TEXT NOT NULL,
                    at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dispatch_offer_pilot
                    ON dispatch_offers(pilot_id,status,deadline);
                CREATE TABLE IF NOT EXISTS dispatch_reservations (
                    pilot_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE REFERENCES dispatch_orders(id),
                    reserved_at REAL NOT NULL
                );
            """)

    def _db(self):
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not 1 <= len(value) <= 64:
            raise DispatchError("invalid_id")
        if not all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in value):
            raise DispatchError("invalid_id")
        return value

    @staticmethod
    def _has_fleet(conn):
        return conn.execute("""SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='fleet_pilots'""").fetchone() is not None

    @staticmethod
    def _is_available(conn, pilot_id, now):
        # A reservation always wins over any client-reported busy=False.
        reserved = conn.execute(
            "SELECT 1 FROM dispatch_reservations WHERE pilot_id=?",
            (pilot_id,)).fetchone()
        if reserved:
            return False
        if not IsolatedDispatch._has_fleet(conn):
            # Earlier standalone synthetic tests have no fleet registry.
            return True
        row = conn.execute("""SELECT f.approved,f.online,f.vehicle_ready,
            f.busy,f.gps_at,f.latitude,f.longitude,i.role,i.verified
            FROM fleet_pilots f JOIN fleet_identities i ON i.user_id=f.user_id
            WHERE f.user_id=?""", (pilot_id,)).fetchone()
        return bool(row and row["role"] == "pilot" and row["verified"]
                    and row["approved"] and row["online"]
                    and row["vehicle_ready"] and not row["busy"]
                    and row["latitude"] is not None
                    and row["longitude"] is not None
                    and row["gps_at"] is not None
                    and 0 <= now - row["gps_at"] < 90)

    def create_test_order(self, order_id):
        """Only for isolated synthetic fixtures, never a real booking endpoint."""
        order_id = self._id(order_id)
        with self._db() as conn:
            conn.execute("INSERT INTO dispatch_orders(id,status) VALUES (?, 'requested')",
                         (order_id,))

    def offer_nearest(self, order_id, eligible_pilots, *, actor_role):
        """Trusted server passes pilots sorted by road ETA; no app-calculated ranking.

        Each item is (pilot_id, road_eta_seconds), supplied by a trusted
        eligibility/location/route service. No fake ETA is calculated here.
        """
        if actor_role != "dispatcher":
            raise DispatchError("forbidden")
        order_id = self._id(order_id)
        pilots = []
        for pilot_id, eta in eligible_pilots:
            pilot_id = self._id(pilot_id)
            if isinstance(eta, bool) or not isinstance(eta, (int, float)) or not 0 <= eta <= 86400:
                raise DispatchError("invalid_eta")
            if pilot_id not in [x[0] for x in pilots]:
                pilots.append((pilot_id, eta))
        pilots.sort(key=lambda pair: (pair[1], pair[0]))
        now = self.clock()
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM dispatch_orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise DispatchError("not_found")
            if order["winner"] is not None or order["status"] in ("assigned", "cancelled"):
                raise DispatchError("already_assigned")
            active = conn.execute("""SELECT 1 FROM dispatch_offers
                WHERE order_id=? AND status='pending' AND deadline>?""",
                (order_id, now)).fetchone()
            if active:
                raise DispatchError("round_active")
            conn.execute("""UPDATE dispatch_offers SET status='expired'
                WHERE order_id=? AND status='pending' AND deadline<=?""",
                (order_id, now))
            used = {r[0] for r in conn.execute(
                "SELECT DISTINCT pilot_id FROM dispatch_offers WHERE order_id=?", (order_id,))}
            # Exclude previously offered pilots, including explicit declines.
            # Revalidate availability under the SAME write transaction that
            # persists offers. A previously ranked pilot may now be busy,
            # revoked, offline, or already reserved for a different order.
            chosen = [pid for pid, _ in pilots
                      if pid not in used and self._is_available(conn, pid, now)][:BATCH_SIZE]
            if not chosen:
                conn.execute("UPDATE dispatch_orders SET status='requested' WHERE id=?", (order_id,))
                return []
            round_no = order["round_no"] + 1
            deadline = now + OFFER_SECONDS
            conn.execute("UPDATE dispatch_orders SET status='offered', round_no=? WHERE id=?",
                         (round_no, order_id))
            conn.executemany("""INSERT INTO dispatch_offers
                (order_id,pilot_id,round_no,deadline,status)
                VALUES (?,?,?,?,'pending')""",
                [(order_id, pid, round_no, deadline) for pid in chosen])
            conn.execute("""INSERT INTO dispatch_events(order_id,pilot_id,event,at)
                VALUES (?,NULL,'offered',?)""", (order_id, now))
            return list(chosen)

    def respond(self, order_id, *, authenticated_pilot_id, accept):
        """Authenticated pilot identity MUST come from a verified server session."""
        order_id = self._id(order_id)
        pilot_id = self._id(authenticated_pilot_id)
        if type(accept) is not bool:
            raise DispatchError("invalid_action")
        now = self.clock()
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM dispatch_orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise DispatchError("not_found")
            if order["winner"] is not None:
                return "already_yours" if order["winner"] == pilot_id else "already_taken"
            if order["status"] != "offered":
                raise DispatchError("no_active_offer")
            offer = conn.execute("""SELECT * FROM dispatch_offers WHERE
                order_id=? AND pilot_id=? AND round_no=?""",
                (order_id, pilot_id, order["round_no"])).fetchone()
            if offer is None:
                raise DispatchError("not_invited")
            if offer["status"] != "pending":
                return offer["status"]
            if now >= offer["deadline"]:
                conn.execute("""UPDATE dispatch_offers SET status='expired'
                    WHERE order_id=? AND pilot_id=? AND round_no=?""",
                    (order_id, pilot_id, order["round_no"]))
                return "expired"
            if not accept:
                conn.execute("""UPDATE dispatch_offers SET status='declined'
                    WHERE order_id=? AND pilot_id=? AND round_no=?""",
                    (order_id, pilot_id, order["round_no"]))
                return "declined"
            # Recheck verified identity, current GPS and vehicle state inside
            # the acceptance transaction. The unique pilot_id reservation
            # prevents winning another order, including across connections.
            if not self._is_available(conn, pilot_id, now):
                return "pilot_unavailable"
            conn.execute("""INSERT INTO dispatch_reservations
                (pilot_id,order_id,reserved_at) VALUES (?,?,?)""",
                (pilot_id, order_id, now))
            conn.execute("""UPDATE dispatch_orders SET status='assigned', winner=?
                WHERE id=? AND status='offered' AND winner IS NULL""",
                (pilot_id, order_id))
            conn.execute("""UPDATE dispatch_offers SET status=CASE
                WHEN pilot_id=? THEN 'accepted' ELSE 'lost' END
                WHERE order_id=? AND round_no=? AND status='pending'""",
                (pilot_id, order_id, order["round_no"]))
            conn.execute("""INSERT INTO dispatch_events(order_id,pilot_id,event,at)
                VALUES (?,?, 'accepted',?)""", (order_id, pilot_id, now))
            return "accepted"

    def release_reservation(self, order_id, *, authenticated_dispatcher):
        """Cancel an assigned synthetic trip and release only its own pilot.

        This is a trusted maintenance action; a genuine dispatcher identity
        must exist in the synthetic fleet registry. No client-originated role.
        """
        order_id = self._id(order_id)
        dispatcher = self._id(authenticated_dispatcher)
        now = self.clock()
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            identity = conn.execute("""SELECT role, verified FROM fleet_identities
                WHERE user_id=?""", (dispatcher,)).fetchone() if self._has_fleet(conn) else None
            if not identity or identity["role"] != "dispatcher" or not identity["verified"]:
                raise DispatchError("forbidden")
            order = conn.execute("SELECT * FROM dispatch_orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise DispatchError("not_found")
            if order["status"] == "cancelled":
                return "already_released"
            if order["status"] != "assigned" or order["winner"] is None:
                raise DispatchError("not_assigned")
            # WHERE on both IDs prevents clearing a reservation belonging to
            # another order, even in an inconsistent or stale client request.
            deleted = conn.execute("""DELETE FROM dispatch_reservations
                WHERE pilot_id=? AND order_id=?""",
                (order["winner"], order_id))
            if deleted.rowcount != 1:
                raise DispatchError("reservation_mismatch")
            conn.execute("""UPDATE dispatch_orders SET status='cancelled'
                WHERE id=?""", (order_id,))
            conn.execute("""INSERT INTO dispatch_events(order_id,pilot_id,event,at)
                VALUES (?,?, 'released',?)""",
                (order_id, order["winner"], now))
            return "released"

    def snapshot(self, order_id):
        order_id = self._id(order_id)
        with self._db() as conn:
            order = conn.execute("SELECT * FROM dispatch_orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise DispatchError("not_found")
            offers = conn.execute("""SELECT pilot_id,round_no,status,deadline FROM
                dispatch_offers WHERE order_id=? ORDER BY round_no,pilot_id""",
                (order_id,)).fetchall()
            return dict(order), [dict(o) for o in offers]
