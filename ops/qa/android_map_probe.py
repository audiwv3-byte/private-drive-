"""Drive the QA29 APK and verify the actual dispatcher marker for its order."""
import time

from urllib.parse import urlsplit

import psycopg
from playwright.sync_api import TimeoutError as BrowserTimeout

import qa29_gps_integration as fixture


def start_pilot(apk, order_id):
    adb = fixture.adb
    adb("install", "-r", str(apk))
    adb("reverse", "tcp:18729", "tcp:18729")
    for name in ("ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION", "POST_NOTIFICATIONS"):
        adb("shell", "pm", "grant", fixture.PACKAGE, "android.permission." + name)
    adb("shell", "cmd", "location", "set-location-enabled", "true")
    adb("shell", "am", "start", "-W", "-n",
        fixture.PACKAGE + "/lt.privatedrive.private_drive.MainActivity")
    button = fixture.find_control("Передавать GPS диспетчеру", order_id=order_id)
    adb("shell", "input", "tap", *button)
    fixture.find_control("Остановить передачу GPS")
    print(f"Android pilot started sharing for dispatcher order {order_id}", flush=True)


# Independently compare the visible icon anchor with the Web Mercator location
# on the displayed Leaflet tiles. This detects swapped coordinates and stale pins.
MARKER_AT_FIX = r"""([lat, lon]) => {
    const icons = document.querySelectorAll('#rasterMap .leaflet-marker-pane .pilot-marker');
    if (icons.length !== 1 || icons[0].title !== 'Пилот выбранного заказа') return false;
    const icon = icons[0], box = icon.getBoundingClientRect(), style = getComputedStyle(icon);
    const x = box.left - parseFloat(style.marginLeft), y = box.top - parseFloat(style.marginTop);
    const map = document.getElementById('rasterMap').getBoundingClientRect();
    if (x < map.left || x > map.right || y < map.top || y > map.bottom) return false;
    for (const tile of document.querySelectorAll('#rasterMap .leaflet-tile-loaded')) {
        const parts = new URL(tile.src).pathname.match(/\/(\d+)\/(\d+)\/(\d+)\.png$/);
        if (!parts) continue;
        const [, zoom, tx, ty] = parts.map(Number);
        const expected = L.CRS.EPSG3857.latLngToPoint([lat, lon], zoom);
        const rect = tile.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const dx = rect.left + (expected.x / 256 - tx) * rect.width - x;
        const dy = rect.top + (expected.y / 256 - ty) * rect.height - y;
        if (Math.abs(dx) <= 2 && Math.abs(dy) <= 2) return true;
    }
    return false;
}"""


def verify_android_fix(page, oid, lat, lon, previous_timestamp):
    fixture.adb("emu", "geo", "fix", str(lon), str(lat))
    path = f"/dispatch/orders/{oid}/gps"
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        response = page.wait_for_event("response", predicate=lambda r: urlsplit(r.url).path == path,
                                       timeout=15000)
        assert response.ok
        gps = response.json()
        if (gps.get("available") and gps["captured_at"] > previous_timestamp
                and abs(gps["latitude"]-lat) < 0.0001 and abs(gps["longitude"]-lon) < 0.0001):
            break
    else:
        raise AssertionError(f"Dispatcher browser did not receive emulator fix {lat}, {lon}")
    with psycopg.connect(fixture.DSN) as db:
        row = db.execute("""SELECT latitude, longitude, captured_at FROM public.pd_qa27_gps
                            WHERE order_id = %s AND pilot_id = %s""", (oid, "qa29-pilot")).fetchone()
    assert row and abs(row[0]-lat) < 0.0001 and abs(row[1]-lon) < 0.0001 and row[2] >= gps["captured_at"]
    try:
        page.wait_for_function(MARKER_AT_FIX, arg=[lat, lon], timeout=12000)
    except BrowserTimeout:
        print("Map geometry at timeout:", page.evaluate("""() => {
            const sample = selector => [...document.querySelectorAll(selector)].slice(0,2).map(el => ({
                label: el.title, url: el.src, cls: el.className, rect: el.getBoundingClientRect().toJSON(),
                margin: getComputedStyle(el).margin, transform: el.style.transform
            }));
            return {map: sample('#rasterMap'), icons: sample('.pilot-marker'),
                    tiles: sample('.leaflet-tile'), loaded: sample('.leaflet-tile-loaded')};
        }"""), flush=True)
        raise
    print(f"PASS: {oid} Android, PostgreSQL, dispatcher response and visible marker agree at {lat}, {lon}",
          flush=True)
    return gps["captured_at"]


def is_asleep():
    return "mWakefulness=Asleep" in fixture.adb("shell", "dumpsys", "power")
