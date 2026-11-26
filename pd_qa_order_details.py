"""Strict, payment-free passenger booking metadata contract (QA only).

Amounts are previews supplied by the client and never authoritative prices.
"""
import json

FIELDS = frozenset({"ride_type", "round_trip", "advance_booking", "tariff",
                    "fare_preview_eur", "fare_requires_quote", "extras",
                    "wishes", "preferences", "passengers", "luggage"})

def normalize_details(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError("invalid_booking_details")
    if len(json.dumps(value, ensure_ascii=False)) > 4096:
        raise ValueError("booking_details_too_large")
    result = dict(value)
    for key in ("ride_type", "tariff", "wishes", "luggage"):
        if key in result and (not isinstance(result[key], str) or
                              len(result[key]) > (1000 if key == "wishes" else 120)):
            raise ValueError("invalid_booking_details")
    for key in ("round_trip", "advance_booking", "fare_requires_quote"):
        if key in result and not isinstance(result[key], bool):
            raise ValueError("invalid_booking_details")
    if "passengers" in result and (type(result["passengers"]) is not int
                                  or not 1 <= result["passengers"] <= 20):
        raise ValueError("invalid_booking_details")
    if "fare_preview_eur" in result and (type(result["fare_preview_eur"]) not in (int, float)
                                       or not 0 <= result["fare_preview_eur"] <= 100000):
        raise ValueError("invalid_booking_details")
    if "extras" in result and (not isinstance(result["extras"], list)
                               or len(result["extras"]) > 30
                               or any(not isinstance(x, str) or len(x) > 120 for x in result["extras"])):
        raise ValueError("invalid_booking_details")
    if "preferences" in result:
        prefs = result["preferences"]
        if not isinstance(prefs, dict) or len(prefs) > 32 or any(
            not isinstance(k, str) or len(k) > 50 or
            not isinstance(v, (str, bool, int, float, list, type(None))) or
            isinstance(v, str) and len(v) > 200 or
            isinstance(v, list) and (len(v) > 5 or
                any(not isinstance(item, str) or len(item) > 120 for item in v))
            for k,v in prefs.items()
        ):
            raise ValueError("invalid_booking_details")
    return result
