import json
import os
import ssl
import subprocess
import threading
import urllib.error
import urllib.request
import uuid
from werkzeug.serving import make_server
from ops.qa.qa42_local_https import prepare

def test_local_tls_dispatch(tmp_path):
    app, tokens, dispatch, csrf = prepare()
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1",
        "-subj","/CN=127.0.0.1","-addext","subjectAltName=IP:127.0.0.1",
        "-keyout",str(key),"-out",str(cert)], check=True, capture_output=True)
    server = make_server("127.0.0.1", 443, app, ssl_context=(str(cert), str(key)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = ssl.create_default_context(cafile=str(cert))
    def call(path, headers=None, data=None):
        req = urllib.request.Request("https://127.0.0.1"+path,
            headers=headers or {}, data=data)
        try:
            with urllib.request.urlopen(req, context=context, timeout=10) as res:
                return res.status, json.load(res)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)
    try:
        try:
            urllib.request.urlopen("https://127.0.0.1/dispatch/orders/state",
                context=ssl.create_default_context(), timeout=5)
        except urllib.error.URLError as exc:
            assert isinstance(exc.reason, ssl.SSLCertVerificationError)
        else:
            raise AssertionError("Untrusted certificate accepted")
        assert call("/dispatch/orders/state")[0] == 401
        headers = {"Authorization": "Bearer "+tokens["passenger"], "Content-Type":"application/json"}
        status, order = call("/native-orders", headers, json.dumps({
            "request_id":str(uuid.uuid4()),"from":"Synthetic A","to":"Synthetic B",
            "trip_date":"2030-01-01","trip_time":"12:00"}).encode())
        assert status == 201, order
        status, queue = call("/dispatch/orders/state", {"X-Telegram-Init-Data":dispatch})
        assert status == 200, queue
        assert [x["id"] for x in queue["orders"]] == [order["order_id"]]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
