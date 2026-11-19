#!/usr/bin/env python3
"""Smoke test the real public raster URLs used by the isolated demo maps.

This is a network integration gate, not a mock widget assertion. It must run
before an APK is uploaded. Production and server endpoints are untouched.
"""
from __future__ import annotations

import math
import urllib.error
import urllib.request


def tile_at(latitude: float, longitude: float, zoom: int) -> tuple[int, int, int]:
    n = 1 << zoom
    x = int((longitude + 180.0) / 360.0 * n)
    lat_radians = math.radians(latitude)
    y = int((1.0 - math.asinh(math.tan(lat_radians)) / math.pi) / 2.0 * n)
    assert 0 <= x < n and 0 <= y < n
    return zoom, x, y


def probe(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PRIVATE DRIVE map smoke test (demo Android client)",
            "Accept": "image/png,image/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            signature = response.read(8)
        valid = status == 200 and content_type.startswith("image/") and (
            signature == b"\x89PNG\r\n\x1a\n"
            or signature.startswith(b"\xff\xd8\xff")
            or signature.startswith(b"RIFF")
        )
        return valid, f"HTTP {status}, {content_type}, valid_image={valid}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    z, x, y = tile_at(54.6872, 25.2797, 10)
    print(f"Vilnius city centre actual raster coordinates: {z}/{x}/{y}", flush=True)
    sources = {
        "OSM day": f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "CARTO day": f"https://a.basemaps.cartocdn.com/voyager/{z}/{x}/{y}.png",
        "CARTO night": f"https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    }
    successes = set()
    for name, url in sources.items():
        ok, details = probe(url)
        print(f"{name}: {details}: {url}", flush=True)
        if ok:
            successes.add(name)
    if not ({"OSM day", "CARTO day"} & successes):
        raise SystemExit("No working daytime map source. Do not publish APK.")
    if "CARTO night" not in successes:
        raise SystemExit("Night map endpoint failed. Do not publish APK.")
    print("PASS: actual valid raster image data from day and night providers", flush=True)


if __name__ == "__main__":
    main()
