"""Exercise the staging map template against the pinned QA29 loopback fixture."""
import argparse
import base64
from collections import Counter
import json
import os
import secrets
from pathlib import Path
import shutil
import time
from threading import Thread
from types import SimpleNamespace
from urllib.parse import urlsplit

from flask import Flask
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

from pd_web_dispatcher import register
from playwright.sync_api import sync_playwright

import qa29_gps_integration as fixture


def run(android_apk=None):
    oid = fixture.OID_FILE.read_text().strip()
    read_path = f"/dispatch/orders/{oid}/gps"
    write_path = f"/native-pilot-orders/{oid}/gps"
    pilot = {"Authorization": "Bearer " + fixture.PILOT}
    admin = fixture.signed(201)
    password = secrets.token_urlsafe(24)
    os.environ.update({
        "PD_DISPATCH_SESSION_SECRET": secrets.token_hex(32),
        "PD_DISPATCH_PASSWORD_HASH": generate_password_hash(password),
        "PD_DISPATCH_ADMIN_ID": "201", "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1", "PD_QA27_GPS": "1",
        "PD_DISPATCH_ORDERS_INGEST_SECRET": secrets.token_hex(32),
        "PD_DISPATCH_ORDERS_DATABASE_URL": fixture.DSN.replace("postgres:isolated-test@", "qa29_api:synthetic-api@"),
        "PD_DISPATCH_TEST_SYNC": "1",
    })
    app = Flask(__name__)
    assert register(app, SimpleNamespace(ADMIN_IDS={201}, is_admin=lambda uid: uid == 201))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    web_host = f"127.0.0.1:{server.server_port}"
    web_url = f"http://{web_host}"
    empty_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jgGQAAAAASUVORK5CYII=")
    browser_requests = Counter()
    errors = []
    legacy_points = []
    observations = []

    def route(request_route):
        url = urlsplit(request_route.request.url)
        path = url.path
        if url.netloc == web_host:
            browser_requests[path] += 1
            if path == "/dispatch/test-sync/state":
                return request_route.fulfill(json={"pilots": legacy_points})
            return request_route.continue_()
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
        anonymous = page.request.get(web_url + read_path)
        assert anonymous.status == 401 and "no-store" in anonymous.headers["cache-control"]
        page.goto(web_url + "/dispatch/login")
        page.locator('input[name=password]').fill(password)
        page.locator('button[type=submit], form button').first.click()
        page.wait_for_url(web_url + "/dispatch")
        print("Unsigned browser GPS read denied; signed-in dispatcher opened /dispatch", flush=True)
        card = page.locator("#ordersList .card").filter(has_text="Synthetic A")
        card.wait_for()
        assert "Пилот назначен" in card.inner_text()
        card.get_by_role("button", name="Пилот на карте").click()
        page.locator("#rasterMap.leaflet-container").wait_for(state="visible")
        page.locator(".leaflet-map-pane").wait_for(state="attached")
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
        if android_apk:
            from android_map_probe import is_asleep, start_pilot, verify_android_fix
            assert fixture.request(read_path, headers=admin) == {"available": False}
            assert markers.count() == 0
            lat, lon = fixes[0]
            fixture.adb("emu", "geo", "fix", str(lon), str(lat))
            start_pilot(android_apk, oid)
            first_timestamp = verify_android_fix(page, oid, *fixes[0], 0)
            observe("order_fix_1")
            fixture.adb("shell", "input", "keyevent", "KEYCODE_HOME")
            fixture.adb("shell", "input", "keyevent", "KEYCODE_SLEEP")
            fixture.poll(is_asleep, bool, "Android screen asleep")
            verify_android_fix(page, oid, *fixes[1], first_timestamp)
            assert is_asleep(), "Emulator woke up during the second GPS check"
            observe("order_fix_2")
        else:
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

        if android_apk:
            import psycopg
            assert page.request.get(web_url + read_path).json() == {"available": False}
            with psycopg.connect(fixture.DSN) as db:
                assert db.execute("SELECT count(*) FROM public.pd_qa27_gps WHERE order_id=%s", (oid,)).fetchone()[0] == 0
            assert markers.count() == 0
            print(f"PASS: finished {oid}, no stored fix, browser GPS unavailable and marker removed", flush=True)

        # Independent positive control for the same offline renderer.
        for index, fix in enumerate(fixes):
            legacy_points[:] = [{"id": "pilot_test", "position": list(fix)}]
            observe(f"legacy_control_{index+1}")
        legacy_points.clear()
        observe("legacy_control_removed")
        browser.close()
    server.shutdown()
    server.server_close()

    first, second, finished, control1, control2, removed = [sample["positions"] for sample in observations]
    print("Browser request counts:", dict(browser_requests), "page errors:", errors, flush=True)
    assert len(control1) == len(control2) == 1 and control1 != control2 and not removed, "Leaflet control failed"
    assert not errors, errors
    assert browser_requests[read_path] > 0, "Map did not request GPS for the assigned order"
    assert len(first) == len(second) == 1 and first != second and not finished, "Order marker lifecycle failed"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--android-apk", type=Path)
    run(parser.parse_args().android_apk)
