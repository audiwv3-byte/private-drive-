"""Run the synthetic cabinet API and verify it through a temporary HTTPS tunnel."""
from __future__ import annotations

import json
import mimetypes
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, unquote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pd_native_cabinet_mock import CabinetHandler, CabinetStore, PHOTO, make_mock_server, utc_now
from run_quick_tunnel import drain_tunnel_output, stop


class PreviewHandler(CabinetHandler):
    def do_GET(self):
        if self.path in ("/", "/healthz"):
            self._reply(200, {"status": "ok", "service": "private-drive-cabinet-mock"})
        elif self.path.startswith("/app/") and getattr(self.server, "web_root", None):
            root = self.server.web_root.resolve()
            relative = unquote(urlsplit(self.path).path[len("/app/"):])
            target = (root / (relative or "index.html")).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        else:
            super().do_GET()


def request(url, path, token=None, body=None, expected=200):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    payload = None if body is None else json.dumps(body).encode()
    req = Request(url + path, data=payload, headers=headers)
    try:
        response = urlopen(req, timeout=12)
    except HTTPError as exc:
        response = exc
    with response:
        if response.status != expected:
            raise RuntimeError(f"{path} returned HTTP {response.status}, expected {expected}")
        return json.load(response)


def verify(url, inbox):
    for _ in range(15):
        try:
            health = request(url, "/healthz")
            if health["service"] == "private-drive-cabinet-mock":
                break
        except (OSError, RuntimeError):
            time.sleep(2)
    else:
        raise RuntimeError("Mock API did not answer through HTTPS")

    request(url, "/v1/me", expected=401)
    sessions = {}
    for index, role in enumerate(("passenger", "pilot", "dispatcher"), start=1):
        phone = f"+1202555010{index}"
        challenge = request(url, "/native-auth/request-code", body={
            "channel": "phone", "destination": phone,
        }, expected=202)
        session = request(url, "/native-auth/verify-code", body={
            "challenge_id": challenge["challenge_id"], "code": inbox.pop(phone),
        })
        token = session["access_token"]
        if request(url, "/v1/me", token)["role"] != role:
            raise RuntimeError("Unexpected role after native verification")
        sessions[role] = token

    passenger, pilot, dispatcher = (sessions[r] for r in ("passenger", "pilot", "dispatcher"))
    request(url, "/native-identity/submit", pilot, {"photo": PHOTO})
    photo_id = request(url, "/native-identity/queue", dispatcher)["items"][0]["id"]
    request(url, "/native-identity/decision/" + photo_id, dispatcher, {"decision": "approved"})
    request(url, "/v1/gps", pilot, {
        "online": True, "latitude": 54.7, "longitude": 25.3,
        "seen_at": utc_now().isoformat(),
    })
    trip = request(url, "/v1/trips", passenger, {
        "from": "Synthetic start", "to": "Synthetic finish",
        "departure": utc_now().isoformat(), "client_id": uuid.uuid4().hex,
    }, expected=201)["trip"]
    current = request(url, "/v1/current", dispatcher)
    if current["trip"]["id"] != trip["id"] or current["gps"]["latitude"] != 54.7:
        raise RuntimeError("Dispatcher did not receive the test trip and GPS fix")
    path = "/v1/trips/" + trip["id"]
    request(url, path + "/assign", passenger, {"version": trip["version"]}, expected=403)
    assigned = request(url, path + "/assign", dispatcher, {"version": trip["version"]})["trip"]
    if request(url, "/v1/current", pilot)["trip"]["id"] != trip["id"]:
        raise RuntimeError("Pilot did not receive the assigned test trip")
    message = {"client_id": uuid.uuid4().hex, "text": "Synthetic HTTPS test"}
    for _ in range(2):
        request(url, path + "/messages", pilot, message, expected=201)
    for token in (passenger, dispatcher):
        rows = request(url, path + "/messages", token)["messages"]
        if [row["body"] for row in rows] != [message["text"]]:
            raise RuntimeError("Test message was lost or duplicated")
    request(url, path + "/cancel", passenger, {"version": assigned["version"]})
    request(url, "/v1/gps", pilot, {"online": False})


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudflared", required=True)
    parser.add_argument("--address-file", type=Path, required=True)
    parser.add_argument("--web-root", type=Path, default=None)
    options = parser.parse_args()
    inbox = {}
    with tempfile.TemporaryDirectory(prefix="pd-native-preview-") as temp:
        store = CabinetStore(Path(temp) / "synthetic.sqlite")
        with make_mock_server(store, inbox.__setitem__, handler=PreviewHandler, isolated_qa_auth=True) as server:
            server.web_root = options.web_root
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            tunnel = subprocess.Popen([
                options.cloudflared, "tunnel", "--protocol", "http2", "--no-autoupdate",
                "--url", f"http://127.0.0.1:{server.server_port}",
            ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            urls = queue.Queue()
            threading.Thread(target=drain_tunnel_output, args=(tunnel.stdout, urls), daemon=True).start()
            try:
                url = urls.get(timeout=45)
                server.browser_origin = url
                verify(url, inbox)
                options.address_file.write_text(url + "\n")
                print("HTTPS verified for all three native roles, shared trips, GPS and chat.", flush=True)
                deadline = time.monotonic() + 35 * 60
                while time.monotonic() < deadline:
                    if tunnel.poll() is not None:
                        raise RuntimeError("Temporary HTTPS tunnel stopped")
                    time.sleep(3)
            finally:
                stop(tunnel)
                server.shutdown()
                thread.join()
                store.close()


if __name__ == "__main__":
    main()
