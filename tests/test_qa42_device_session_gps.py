import json
import ssl
import threading
import time
import urllib.request
from urllib.error import HTTPError
import uuid
from ops.qa.qa42_device_https import make_application, make_tls_server

def test_shared_session_and_gps(tmp_path):
    app, tokens, _ = make_application()
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
        assert post("/native-auth/sign-out",tokens["pilot"])[0] == 200
        assert post("/native-auth/session",tokens["pilot"])[0] == 401
        assert post("/native-auth/session",tokens["passenger"])[0] == 200
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
