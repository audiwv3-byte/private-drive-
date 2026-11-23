"""Short-lived passenger fixes for isolated dispatch previews."""

import time

ACTIVE_TRIP_STATES = frozenset({"requested", "assigned", "approaching", "underway"})
LOCATION_TTL = 45


class PassengerLocations:
    """Keep fixes in memory and scope each one to an active trip."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.fixes = {}

    def _discard_expired(self):
        now = self.clock()
        for trip_id, (_, expiry) in list(self.fixes.items()):
            if expiry <= now:
                del self.fixes[trip_id]

    def update(self, trip, payload):
        self._discard_expired()
        trip_id = trip["id"]
        if set(payload) != {"latitude", "longitude"}:
            raise ValueError("invalid_position")
        lat, lon = payload["latitude"], payload["longitude"]
        if lat is None and lon is None:
            self.fixes.pop(trip_id, None)
            return
        if trip["status"] not in ACTIVE_TRIP_STATES:
            raise ValueError("inactive_trip")
        if (type(lat) not in (int, float) or type(lon) not in (int, float)
                or not (-90 <= lat <= 90 and -180 <= lon <= 180)
                or (lat == 0 and lon == 0)):
            raise ValueError("invalid_position")
        self.fixes[trip_id] = ({"latitude": round(lat, 5), "longitude": round(lon, 5)},
                               self.clock() + LOCATION_TTL)

    def snapshot(self, trips):
        self._discard_expired()
        positions = {}
        for trip in trips:
            trip_id = trip["id"]
            if trip["status"] not in ACTIVE_TRIP_STATES:
                self.fixes.pop(trip_id, None)
            elif trip_id in self.fixes:
                point, expiry = self.fixes[trip_id]
                positions[trip_id] = {**point, "expires_in": max(0, expiry - self.clock())}
        return positions
