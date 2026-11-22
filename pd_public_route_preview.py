"""Isolated, read-only route preview for PRIVATE DRIVE staging.

Never imports Telegram app, customer database or payments. Live directions and
autocomplete require a SEPARATE staging ORS_API_KEY; fail closed otherwise.
"""
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict, deque
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request
import pd_fixed_prices

_DIRECTIONS_BASE_URL = "https://api.heigit.org/openrouteservice"
_GEOCODE_BASE_URL = "https://api.heigit.org/pelias/v1"
_LIMITS = defaultdict(deque)


def _rate_limit(action, count=15):
    addr = request.remote_addr or "unknown"
    key = (action, addr)
    now = time.monotonic()
    history = _LIMITS[key]
    while history and history[0] < now - 60:
        history.popleft()
    if len(history) >= count:
        return False
    history.append(now)
    return True


def _normalized_key():
    """Strip accidental copy/paste wrappers, not the key's actual contents."""
    raw = os.getenv("PD_STAGING_ORS_API_KEY", "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1].strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw


def _auth_error_category(exc):
    """Classify a bounded API error body without logging it or the credential."""
    if not isinstance(exc, urllib.error.HTTPError):
        return "NETWORK_OR_UPSTREAM"
    if exc.code != 403:
        return "UPSTREAM_HTTP_" + str(exc.code)
    try:
        body = exc.read(1500).decode("utf-8", "replace").casefold()
    except Exception:
        return "FORBIDDEN_UNCLASSIFIED"
    if "quota exceeded" in body or "rate limit" in body:
        return "QUOTA_OR_RATE_LIMIT"
    if ("invalid api key" in body or "invalid key" in body or
            "access disallowed" in body or "access to this api has been disallowed" in body):
        return "KEY_OR_PERMISSION_REJECTED"
    if "not allowed" in body or "permission" in body or "forbidden" in body:
        return "FORBIDDEN_PERMISSION"
    return "FORBIDDEN_UNCLASSIFIED"


def _request_json(url, payload=None):
    # Caller constructs only hardcoded ORS endpoints, never follows user URLs.
    key = _normalized_key()
    if not key:
        raise RuntimeError("staging geocoding not configured")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"User-Agent": "PrivateDriveStaging/1.0", "Authorization": key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError("routing unavailable")
        raw = response.read(400_001)
        if len(raw) > 400_000:
            raise RuntimeError("routing response too large")
    return json.loads(raw)


_PUBLIC_GEOCODER = "https://photon.komoot.io/api/"
_PUBLIC_ROUTER = "https://routing.openstreetmap.de/routed-car/route/v1/driving/"
_FALLBACK_CACHE = {}
_FALLBACK_GLOBAL_HITS = defaultdict(deque)


def _public_fallback_enabled():
    """Explicitly isolated test service only; never production or Mini App."""
    return (os.getenv("PD_DISPATCH_STAGING_ONLY") == "1" and
            os.getenv("PD_STAGING_PUBLIC_FALLBACK") == "1")


def _public_json(url, kind):
    """Named public demo servers only, bounded requests; fail closed when busy."""
    if not _public_fallback_enabled():
        raise RuntimeError("public fallback disabled")
    host = urllib.parse.urlsplit(url)
    expected = "photon.komoot.io" if kind == "suggest" else "routing.openstreetmap.de"
    if host.scheme != "https" or host.hostname != expected or kind not in ("suggest", "route"):
        raise ValueError("unapproved test API host")
    now = time.monotonic()
    cached = _FALLBACK_CACHE.get(url)
    if cached and now - cached[0] < 600:
        return cached[1]
    log = _FALLBACK_GLOBAL_HITS[kind]
    while log and log[0] < now - 60:
        log.popleft()
    if len(log) >= (12 if kind == "suggest" else 4):
        raise RuntimeError("test routing rate limited")
    log.append(now)
    req = urllib.request.Request(url, headers={
        "User-Agent": "PrivateDriveStaging/1.0 (testing only; contact evrobaltictransfer@gmail.com)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError("test routing upstream unavailable")
        raw = response.read(400_001)
    if len(raw) > 400_000:
        raise RuntimeError("test routing response too large")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("invalid test API response")
    if len(_FALLBACK_CACHE) >= 60:
        _FALLBACK_CACHE.clear()
    _FALLBACK_CACHE[url] = (now, parsed)
    return parsed


def _suggest_fallback(text):
    url = _PUBLIC_GEOCODER + "?" + urllib.parse.urlencode({
        "q": text, "limit": 5, "lat": 54.6872, "lon": 25.2797
    })
    doc = _public_json(url, "suggest")
    suggestions = []
    for feature in doc.get("features", [])[:8]:
        if not isinstance(feature, dict):
            continue
        props, geom = feature.get("properties") or {}, feature.get("geometry") or {}
        point = _coordinates(geom.get("coordinates"))
        if not point:
            continue
        parts = [props.get(k) for k in ("name", "street", "housenumber", "city", "country")]
        label = _text(", ".join(str(p).strip() for p in parts if isinstance(p, str) and p.strip()), 2, 200)
        if label and not any(row["label"] == label for row in suggestions):
            suggestions.append({"label": label, "coordinates": point})
        if len(suggestions) >= 5:
            break
    return suggestions


def _route_fallback(start, end):
    pairs = ";".join(",".join(str(number) for number in point) for point in (start, end))
    url = _PUBLIC_ROUTER + pairs + "?" + urllib.parse.urlencode({
        "overview": "full", "geometries": "geojson", "steps": "false"
    })
    doc = _public_json(url, "route")
    if doc.get("code") != "Ok" or not isinstance(doc.get("routes"), list) or not doc["routes"]:
        raise ValueError("no road route from test provider")
    route = doc["routes"][0]
    return {
        "features": [{
            "properties": {"summary": {
                "distance": route["distance"], "duration": route["duration"]
            }},
            "geometry": route["geometry"]
        }]
    }


def _coordinates(value):
    if not isinstance(value, list) or len(value) != 2:
        return None
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in value):
        return None
    lon, lat = value
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return [round(lon, 6), round(lat, 6)]


def _text(value, minlen=3, maxlen=160):
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    if not minlen <= len(cleaned) <= maxlen or any(ord(x) < 32 for x in cleaned):
        return None
    return cleaned


def _config_decimal(name, default):
    try:
        number = Decimal(os.getenv(name, default))
        if not number.is_finite() or number < 0 or number > 10000:
            return Decimal(default)
        return number
    except Exception:
        return Decimal(default)


def _approved_staging_price(route_data):
    """Only owner-confirmed preview prices, never imported into actual booking app."""
    import unicodedata
    def place(value):
        value = "".join(x for x in unicodedata.normalize("NFKD", str(value).casefold())
                        if not unicodedata.combining(x))
        if re.search(r"\b(vno|airport|аэропорт)\b", value):
            return "vno"
        aliases = {
            "vilnius": r"\b(vilnius|вильнюс|wilno|vilniaus)\b",
            "kaunas": r"\b(kaunas|каунас|kowno)\b",
            "klaipeda": r"\b(klaipeda|клаипеда|клайпеда|klaipėda)\b",
            "warsaw": r"\b(warsaw|warszawa|варшава)\b",
        }
        return next((code for code, pattern in aliases.items()
                     if re.search(pattern, value)), None)
    start, end = place(route_data.get("origin", "")), place(route_data.get("destination", ""))
    if start == "vilnius" and end == "vno" or start == "vno" and end == "vilnius":
        return Decimal("40")
    if start == "vilnius" and end == "kaunas":
        return Decimal("200") if route_data.get("roundtrip") else Decimal("120")
    if start == "vilnius" and end == "klaipeda":
        return Decimal("320")
    if start == "vilnius" and end == "warsaw":
        return Decimal("460")
    return None


def estimate(km, minutes, route_data):
    """Staging-only approved quotes, then existing test fallback (no real order)."""
    fixed = _approved_staging_price(route_data)
    if fixed is not None:
        return fixed, "fixed"
    fixed = pd_fixed_prices.base(route_data)
    if fixed:
        return Decimal(fixed), "fixed"
    base = _config_decimal("PD_STAGING_BASE_FARE_EUR", "8")
    rate_km = _config_decimal("PD_STAGING_RATE_PER_KM_EUR", "0.9")
    rate_min = _config_decimal("PD_STAGING_RATE_PER_MIN_EUR", "0.0")
    minimum = _config_decimal("PD_STAGING_MIN_FARE_EUR", "25")
    factor = _config_decimal("PD_STAGING_ROUNDTRIP_FACTOR", "2")
    demand = _config_decimal("PD_STAGING_DEMAND_MULTIPLIER", "1")
    empty = _config_decimal("PD_STAGING_EMPTY_RETURN_FACTOR", "0")
    km = Decimal(str(km))
    minutes = Decimal(str(minutes))
    if not (0 < km < 5000 and 0 < minutes < 10000):
        raise ValueError("invalid route summary")
    price = max(minimum, base + rate_km * km + rate_min * minutes)
    if route_data.get("roundtrip"):
        price *= factor
    price = price * demand + empty * rate_km * km
    return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "distance"


def register(app):
    @app.get("/preview/api/suggest")
    def suggest():
        if not _rate_limit("suggest", 15):
            return jsonify(error="Слишком много запросов"), 429
        text = _text(request.args.get("q", ""))
        if not text:
            return jsonify(error="Введите не менее 3 символов"), 400
        if not _normalized_key() and not _public_fallback_enabled():
            return jsonify(available=False, suggestions=[], reason="Сервис подсказок пока не подключён"), 200
        url = _GEOCODE_BASE_URL + "/autocomplete?" + urllib.parse.urlencode({
            "text": text, "size": 5, "focus.point.lat": 54.6872,
            "focus.point.lon": 25.2797
        })
        try:
            if not _normalized_key():
                return jsonify(available=True, suggestions=_suggest_fallback(text), provider="test-photon")
            try:
                doc = _request_json(url)
            except urllib.error.HTTPError as exc:
                if exc.code not in (401, 403) or not _public_fallback_enabled():
                    raise
                return jsonify(available=True, suggestions=_suggest_fallback(text), provider="test-photon")
            suggestions = []
            for feature in doc.get("features", [])[:8]:
                if not isinstance(feature, dict):
                    continue
                props = feature.get("properties") or {}
                geometry = feature.get("geometry") or {}
                label = _text(props.get("label"), 2, 200)
                point = _coordinates(geometry.get("coordinates"))
                if label and point:
                    suggestions.append({"label": label, "coordinates": point})
                if len(suggestions) == 5:
                    break
            return jsonify(available=True, suggestions=suggestions, provider="heigit")
        except Exception:
            return jsonify(available=False, suggestions=[], reason="Подсказки временно недоступны"), 503

    @app.post("/preview/api/route")
    def route_preview():
        if not _rate_limit("route", 8):
            return jsonify(error="Слишком много запросов"), 429
        if request.content_length is not None and request.content_length > 2048:
            return jsonify(error="Слишком большой запрос"), 413
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            return jsonify(error="Некорректный запрос"), 400
        origin = _text(d.get("origin"), 2, 200)
        destination = _text(d.get("destination"), 2, 200)
        start = _coordinates(d.get("origin_coordinates"))
        end = _coordinates(d.get("destination_coordinates"))
        if not origin or not destination or origin.casefold() == destination.casefold():
            return jsonify(error="Укажи два разных адреса"), 400
        if not start or not end or start == end:
            return jsonify(error="Выбери оба адреса из подсказок или используй GPS"), 400
        if d.get("roundtrip") not in (True, False):
            return jsonify(error="Неверный тип поездки"), 400
        category = d.get("category")
        if category not in ("comfort", "economy", "business", "minivan"):
            return jsonify(error="Выбери класс автомобиля"), 400
        if not _normalized_key() and not _public_fallback_enabled():
            return jsonify(available=False, reason="Маршрутизация пока не подключена"), 200
        try:
            fallback_used = False
            if not _normalized_key():
                geojson = _route_fallback(start, end)
                fallback_used = True
            else:
                try:
                    geojson = _request_json(_DIRECTIONS_BASE_URL + "/v2/directions/driving-car/geojson",
                                            {"coordinates": [start, end]})
                except urllib.error.HTTPError as exc:
                    if exc.code not in (401, 403) or not _public_fallback_enabled():
                        raise
                    geojson = _route_fallback(start, end)
                    fallback_used = True
            feature = geojson["features"][0]
            summary = feature["properties"]["summary"]
            coords = feature["geometry"]["coordinates"]
            km = float(summary["distance"]) / 1000.0
            minutes = float(summary["duration"]) / 60.0
            if not isinstance(coords, list) or not 2 <= len(coords) <= 15000:
                raise ValueError("invalid geometry")
            # Preserve geometry and route even when class-specific tariffs are unknown.
            result = {"available": True, "km": round(km, 2),
                      "minutes": round(minutes), "road_coordinates": coords,
                      "price": None, "currency": "EUR",
                      "note": "Без учёта пробок. Данные для предпросмотра, без заказа.",
                      "provider": "test-osrm" if fallback_used else "heigit"}
            if fallback_used:
                result["note"] += " Тестовый публичный маршрутизатор, не для реальных заказов."
            if category == "comfort":
                price, source = estimate(km, minutes, {
                    "origin": origin, "destination": destination,
                    "roundtrip": d["roundtrip"]
                })
                result["price"] = str(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                result["price_source"] = source
                result["note"] += " Тариф по тестовым настройкам, не оферта."
            else:
                result["note"] += " Тариф этого класса ещё не настроен."
            return jsonify(result)
        except Exception:
            return jsonify(available=False, reason="Маршрут временно недоступен"), 503
