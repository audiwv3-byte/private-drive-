"""Exercise the staging map template against the pinned QA29 loopback fixture."""
import base64
from collections import Counter
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit

from jinja2 import Environment
from playwright.sync_api import sync_playwright

import qa29_gps_integration as fixture


def run():
    oid = fixture.OID_FILE.read_text().strip()
    read_path = f"/dispatch/orders/{oid}/gps"
    write_path = f"/native-pilot-orders/{oid}/gps"
    pilot = {"Authorization": "Bearer " + fixture.PILOT}
    admin = fixture.signed(201)
    template = Environment(autoescape=True).from_string(Path("pd_dispatcher_mapbox.html").read_text())
    html = template.render(mapbox_token="", persistent_queue_enabled=True, test_sync_enabled=False,
                           gps_sync_enabled=True, test_queue_link="/dispatch/map?queue=test",
                           pilot_availability_enabled=True, csrf=fixture.CSRF)
    empty_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jgGQAAAAASUVORK5CYII=")
    browser_requests = Counter()
    errors = []
    legacy_points = []
    observations = []

    def route(request_route):
        url = urlsplit(request_route.request.url)
        path = url.path
        if url.netloc == urlsplit(fixture.BASE).netloc:
            browser_requests[path] += 1
            if path == "/dispatch/map":
                return request_route.fulfill(body=html, content_type="text/html; charset=utf-8")
            if path == "/dispatch/test-sync/state":
                return request_route.fulfill(json={"pilots": legacy_points})
            if path.startswith("/dispatch/orders/"):
                return request_route.continue_(headers={**request_route.request.headers, **admin})
        if url.netloc == "unpkg.com" and path in ("/leaflet@1.9.4/dist/leaflet.js", "/leaflet@1.9.4/dist/leaflet.css"):
            filename = Path(path).name
            mime = "text/javascript" if filename.endswith(".js") else "text/css"
            return request_route.fulfill(path=filename, content_type=mime, headers={"Access-Control-Allow-Origin": "*"})
        if url.netloc == "tile.openstreetmap.org":
            return request_route.fulfill(body=empty_png, content_type="image/png")
        return request_route.abort()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=shutil.which("google-chrome"), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.route("**/*", route)
        page.goto(fixture.BASE + "/dispatch/map")
        card = page.locator("#ordersList .card").filter(has_text="Synthetic A")
        card.wait_for()
        assert "Пилот назначен" in card.inner_text()
        card.click()
        page.locator(".leaflet-map-pane").wait_for()
        markers = page.locator(".leaflet-marker-pane .pilot-marker")
        print("Assigned order visible; 2D Leaflet map initialized", flush=True)

        def observe(label):
            # Each sample includes a full new order-list refresh and a legacy GPS refresh.
            for path in ("/dispatch/orders/state", "/dispatch/test-sync/state"):
                page.wait_for_event("response", predicate=lambda response: urlsplit(response.url).path == path,
                                    timeout=10000)
            page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")
            positions = markers.evaluate_all("nodes => nodes.map(node => node.style.transform)")
            sample = dict(stage=label, positions=positions, order=card.inner_text(),
                          gps_browser_requests=browser_requests[read_path])
            observations.append(sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            return positions

        fixes = [(54.6872, 25.2797), (54.6906, 25.2980)]
        for index, (lat, lon) in enumerate(fixes):
            fix = dict(enabled=True, latitude=lat, longitude=lon, captured_at=int(time.time()))
            fixture.request(write_path, "POST", fix, pilot)
            gps = fixture.request(read_path, headers=admin)
            assert gps["available"] and (gps["latitude"], gps["longitude"]) == (lat, lon)
            observe(f"order_fix_{index+1}")
        for action in ("approach", "start", "finish"):
            status = fixture.request("/native-pilot-orders", "PATCH", {"order_id": oid, "action": action}, pilot)
        assert status["status"] == "finished"
        assert fixture.request(read_path, headers=admin) == {"available": False}
        observe("order_finished")
        assert "Завершён" in card.inner_text()

        # Independent positive control for the same offline renderer.
        for index, fix in enumerate(fixes):
            legacy_points[:] = [{"id": "pilot_test", "position": list(fix)}]
            observe(f"legacy_control_{index+1}")
        legacy_points.clear()
        observe("legacy_control_removed")
        browser.close()

    first, second, finished, control1, control2, removed = [sample["positions"] for sample in observations]
    print("Browser request counts:", dict(browser_requests), "page errors:", errors, flush=True)
    assert len(control1) == len(control2) == 1 and control1 != control2 and not removed, "Leaflet control failed"
    assert not errors, errors
    assert browser_requests[read_path] > 0, "Map did not request GPS for the assigned order"
    assert len(first) == len(second) == 1 and first != second and not finished, "Order marker lifecycle failed"


if __name__ == "__main__":
    run()
