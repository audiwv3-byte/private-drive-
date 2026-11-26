"""Validated, non-payment quote for native bookings in the isolated dispatcher.

The fixed Sedan amounts mirror the already approved passenger UI.
Unknown routes/extras are ALWAYS "on request", never zero-priced.
"""
import re

APPROVED_TRANSFER_EUR = {
    "вильнюс|аэропорт вильнюса": 40,
    "аэропорт вильнюса|вильнюс": 40,
    "вильнюс|каунас": 110,
    "вильнюс|клайпеда": 230,
    "вильнюс|паневежис": 120,
    "вильнюс|кедайняй": 130,
    "вильнюс|шяуляй": 200,
    "вильнюс|мариямполе": 130,
    "вильнюс|алитус": 100,
    "вильнюс|друскининкай": 120,
    "вильнюс|бирштонас": 90,
    "вильнюс|утена": 115,
    "вильнюс|кибартай": 160,
    "вильнюс|панямуне": 200,
    "вильнюс|рига": 250,
    "вильнюс|варшава": 400,
}
# Any non-standard extra needs a dispatcher-approved quote.
KNOWN_EXTRAS = frozenset({
    "meet_sign", "sober_driver", "pets", "music", "flowers", "coffee",
    "water", "quiet_ride", "luggage_help", "jumpstart", "delivery",
})
ON_REQUEST_EXTRAS = frozenset({
    "pets", "flowers", "coffee", "water", "jumpstart", "delivery",
})
TEXT_PREFERENCES = frozenset({"radio", "tracks", "temperature", "wishes"})


def validated_details(data, *, origin, destination):
    """Strictly validate optional booking details; no payments or client-set price."""
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - {
        "ride_type", "round_trip", "extras", "preferences"
    }:
        raise ValueError("invalid_details")
    kind = data.get("ride_type", "transfer")
    if kind not in ("transfer", "taxi", "delivery", "jumpstart"):
        raise ValueError("invalid_ride_type")
    round_trip = data.get("round_trip", False)
    if type(round_trip) is not bool:
        raise ValueError("invalid_round_trip")
    extras = data.get("extras", [])
    if not isinstance(extras, list) or len(extras) > len(KNOWN_EXTRAS) or (
        any(not isinstance(x, str) or x not in KNOWN_EXTRAS for x in extras)
    ) or len(extras) != len(set(extras)):
        raise ValueError("invalid_extras")
    preferences = data.get("preferences", {})
    if not isinstance(preferences, dict) or set(preferences) - TEXT_PREFERENCES:
        raise ValueError("invalid_preferences")
    for key, value in preferences.items():
        if key == "tracks":
            if not isinstance(value, list) or len(value) > 3 or any(
                not isinstance(track, str) or len(track.strip()) > 120
                for track in value
            ):
                raise ValueError("invalid_tracks")
        elif key == "temperature":
            if type(value) not in (int, float) or not 18 <= value <= 26:
                raise ValueError("invalid_temperature")
        elif not isinstance(value, str) or len(value.strip()) > (500 if key == "wishes" else 100):
            raise ValueError("invalid_preference")
    if kind in ("delivery", "jumpstart"):
        if round_trip or extras or set(preferences) - {"wishes"}:
            raise ValueError("invalid_service_details")
        if kind == "jumpstart" and destination != "Помощь на месте":
            raise ValueError("invalid_service_destination")
        return {"ride_type": kind, "round_trip": False, "extras": [],
                "preferences": preferences, "quote_required": False,
                "quoted_total_cents": 2000, "currency": "EUR"}
    base = None
    if kind == "transfer":
        route = f"{origin.strip().casefold()}|{destination.strip().casefold()}"
        if round_trip:
            # Only this return trip has a separately approved fixed tariff.
            if route == "вильнюс|каунас":
                base = 20000
        else:
            known = APPROVED_TRANSFER_EUR.get(route)
            if known is not None:
                base = known * 100
    quote_required = base is None or bool(ON_REQUEST_EXTRAS.intersection(extras))
    amount = None if quote_required else (
        base * (2 if "sober_driver" in extras else 1)
        + (1500 if "meet_sign" in extras else 0)
    )
    return {
        "ride_type": kind,
        "round_trip": round_trip,
        "extras": extras,
        "preferences": preferences,
        "quote_required": quote_required,
        "quoted_total_cents": amount,
        "currency": "EUR",
    }
