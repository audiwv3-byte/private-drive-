import json
import ssl
import threading
import time
import urllib.request
from urllib.error import HTTPError, URLError
import uuid
import os
import subprocess
import base64
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from ops.qa.qa42_device_https import make_application, make_tls_server

def test_shared_session_and_gps(tmp_path):
    app, tokens, password = make_application()
    certs = tmp_path / "tls"
    server = make_tls_server("127.0.0.1", certs, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "https://127.0.0.1"
    context = ssl.create_default_context(cafile=str(certs/"ca.pem"))
    def post(path, token=None, body=None):
        headers = {"Content-Type":"application/json"}
        if token: headers["Authorization"] = "Bearer "+token
        request = urllib.request.Request(base+path, data=json.dumps(body or {}).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, context=context, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)
    try:
        with pytest.raises(URLError) as rejected:
            urllib.request.urlopen(base + "/dispatch/login", context=ssl.create_default_context(), timeout=10)
        assert isinstance(rejected.value.reason, ssl.SSLCertVerificationError)
        assert post("/native-auth/session")[0] == 401
        status, session = post("/native-auth/session", tokens["pilot"])
        assert status == 200 and session["role"] == "pilot", session
        assert post("/native-auth/request-code")[0] == 503
        assert post("/native-auth/telegram/start")[0] == 503
        status, order = post("/native-orders", tokens["passenger"], {
            "request_id":str(uuid.uuid4()), "from":"QA synthetic A", "to":"QA synthetic B",
            "trip_date":"2030-01-01", "trip_time":"12:00"})
        assert status == 201, order
        gps = "/native-pilot-orders/"+order["order_id"]+"/gps"
        fix = {"enabled":True,"latitude":54.68,"longitude":25.28,"captured_at":int(time.time())}
        assert post(gps,None,fix)[0] == 401
        assert post(gps,tokens["passenger"],fix)[0] == 403
        assert post(gps,tokens["pilot"],fix)[0] == 404
        home = tmp_path / "browser-home"
        nss = home / ".pki" / "nssdb"
        nss.mkdir(parents=True)
        subprocess.run(["certutil","-N","--empty-password","-d","sql:"+str(nss)],check=True)
        subprocess.run(["certutil","-A","-d","sql:"+str(nss),"-n","QA42 CA","-t","C,,",
                        "-i",str(certs/"ca.pem")],check=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(env={**os.environ,"HOME":str(home)})
            page = browser.new_page(viewport={"width":1440,"height":900})
            def route(r):
                url = r.request.url
                if url.startswith(base+"/"):
                    return r.continue_()
                if url in ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
                           "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"):
                    name = url.rsplit("/",1)[1]
                    return r.fulfill(path=str(Path(name)),content_type="text/javascript" if name.endswith(".js") else "text/css")
                if url.startswith("https://tile.openstreetmap.org/"):
                    return r.fulfill(body=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII="),content_type="image/png")
                return r.abort()
            page.route("**/*",route)
            page.goto(base+"/dispatch/login")
            page.locator("input[name=password]").fill(password)
            page.locator("button[type=submit], form button").first.click()
            page.wait_for_url(base+"/dispatch")
            # Browser fetch uses the same trusted certificate and session cookie.
            def browser_get(path):
                return page.evaluate("async p => {const r=await fetch(p); return [r.status,await r.json()]}",path)
            code, candidates = browser_get("/dispatch/orders/eligible-pilots")
            assert code == 200 and {"id":"qa39-pilot"} in candidates["pilots"], candidates
            card = page.locator("#ordersList .card").filter(has_text="QA synthetic A")
            card.wait_for()
            # Use the actual dispatcher UI assignment controls.
            from urllib.parse import urlencode
            csrf = page.locator('input[name=csrf]').first.get_attribute("value") if page.locator('input[name=csrf]').count() else None
            if not csrf:
                import re
                match = re.search(r'(?:csrf|CSRF)\\s*[:=]\\s*["\x27]([^"\x27]+)',page.content())
                assert match, "Dispatcher CSRF missing"
                csrf = match.group(1)
            assigned = page.evaluate("""async ([p, body]) => {
                const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});
                return [r.status,await r.json()];
            }""",["/dispatch/orders/"+order["order_id"]+"/assign",urlencode({"csrf":csrf,"pilot_id":"qa39-pilot"})])
            assert assigned[0] == 200, assigned
            card.get_by_role("button",name="Пилот на карте").wait_for()
            card.get_by_role("button",name="Пилот на карте").click()
            markers = page.locator("#rasterMap .leaflet-marker-pane .pilot-marker")
            fix["captured_at"] = int(time.time())
            assert post(gps,tokens["pilot"],fix)[0] == 200
            read = "/dispatch/orders/"+order["order_id"]+"/gps"
            assert browser_get(read)[1]["available"] is True
            markers.wait_for(state="visible",timeout=15000)
            time.sleep(1.1)
            assert post(gps,tokens["pilot"],{"enabled":False,"captured_at":int(time.time())})[0] == 200
            assert browser_get(read)[1] == {"available":False}
            markers.wait_for(state="detached",timeout=15000)
            browser.close()
        assert post("/native-auth/sign-out",tokens["pilot"])[0] == 200
        assert post("/native-auth/session",tokens["pilot"])[0] == 401
        assert post("/native-auth/session",tokens["passenger"])[0] == 200
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
