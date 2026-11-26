import os
import ssl
import json
import subprocess
import threading
import urllib.request
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from ops.qa.qa42_device_https import make_application, make_tls_server

def test_shared_https_dispatcher(tmp_path):
    app, tokens, password = make_application()
    certs = tmp_path / "tls"
    server = make_tls_server("127.0.0.1", certs, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "https://127.0.0.1"
    context = ssl.create_default_context(cafile=str(certs / "ca.pem"))
    try:
        for platform in ("android", "ios"):
            payload = json.dumps({"request_id":str(uuid.uuid4()),"from":"QA42 "+platform,
                "to":"Synthetic destination","trip_date":"2030-01-01","trip_time":"12:00"}).encode()
            req = urllib.request.Request(base+"/native-orders", data=payload, headers={
                "Authorization":"Bearer "+tokens["passenger"],"Content-Type":"application/json",
                "X-PD-Native-Platform":platform})
            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                assert response.status == 201
        # Chromium uses a dedicated temporary NSS trust store; no TLS bypass.
        home = tmp_path / "browser-home"
        nss = home / ".pki" / "nssdb"
        nss.mkdir(parents=True)
        subprocess.run(["certutil","-N","--empty-password","-d","sql:"+str(nss)],check=True)
        subprocess.run(["certutil","-A","-d","sql:"+str(nss),"-n","QA42 CA","-t","C,,",
                        "-i",str(certs/"ca.pem")],check=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(env={**os.environ,"HOME":str(home)})
            page = browser.new_page()
            page.route("**/*",lambda route: route.continue_() if route.request.url.startswith(base+"/") else route.abort())
            assert page.request.get(base+"/dispatch/orders/state",ignore_https_errors=True).status == 401
            page.goto(base+"/dispatch/login")
            page.locator("input[name=password]").fill(password)
            page.locator("button[type=submit], form button").first.click()
            page.wait_for_url(base+"/dispatch")
            page.locator("#ordersList .card").filter(has_text="QA42 android").wait_for()
            page.locator("#ordersList .card").filter(has_text="QA42 ios").wait_for()
            browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
