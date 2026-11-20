"""Start a *temporary* Cloudflare Quick Tunnel to an isolated demo server.

This script never deploys to production, creates real orders or charges money.
Run only with explicit PD_DEMO_PUBLIC_TUNNEL=YES on a dedicated testing PC.
"""
from __future__ import annotations

import http.client
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com\b")
MAX_SECONDS = 20 * 60
# The ONLY browser origin allowed for the existing disposable Netlify preview.
SAFARI_PREVIEW_ORIGIN = "https://luxury-mochi-84e459.netlify.app"


def require_explicit_opt_in(env, find_executable=shutil.which):
    if env.get("PD_DEMO_PUBLIC_TUNNEL") != "YES":
        raise RuntimeError("Public test tunnel disabled; set PD_DEMO_PUBLIC_TUNNEL=YES explicitly")
    if env.get("PD_DEMO_BROWSER_ORIGIN") not in (None, SAFARI_PREVIEW_ORIGIN):
        raise RuntimeError("Browser origin must match the existing isolated Safari preview")
    if any(env.get(k) for k in ("PD_DEMO_PASSENGER_TOKEN", "PD_DEMO_PILOT_TOKEN", "PD_DEMO_DISPATCHER_TOKEN")):
        raise RuntimeError("Remove pre-existing PD_DEMO_*_TOKEN variables: generated throwaway tokens are required")
    binary = find_executable("cloudflared")
    if not binary:
        raise RuntimeError("Install official cloudflared before starting a Quick Tunnel")
    return binary


def choose_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(port, token, process, *, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Isolated demo server failed to start")
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/v1/me", headers={"Authorization": "Bearer " + token})
            response = conn.getresponse()
            response.read()
            conn.close()
            if response.status == 200:
                return
        except OSError:
            pass
        time.sleep(0.15)
    raise RuntimeError("Local demo server did not become healthy")


def seed_synthetic_chat_trip(port, credentials):
    """Prepare one fake assigned trip so both mobile clients can chat.

    This never contacts production. The disposable SQLite database is removed
    after the short test session.
    """
    def request(method, route, role, payload):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        headers = {"Authorization": "Bearer " + credentials[role]}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        try:
            conn.request(method, route, body=encoded, headers=headers)
            response = conn.getresponse()
            status = response.status
            data = json.loads(response.read())
        finally:
            conn.close()
        if status not in (200, 201):
            raise RuntimeError("Cannot seed a synthetic chat trip (HTTP " + str(status) + ")")
        return data

    created = request("POST", "/v1/trips", "passenger", {
        "from": "DEMO: синтетический адрес A",
        "to": "DEMO: синтетический адрес B",
        "payment": "Карта",
    })["trip"]
    assigned = request(
        "POST", "/v1/trips/" + created["id"] + "/assign", "dispatcher",
        {"pilot": "pilot_test", "version": created["version"]},
    )["trip"]
    if assigned["status"] != "assigned" or assigned["pilot"] != "pilot_test":
        raise RuntimeError("Synthetic trip was not assigned to demo pilot")
    return assigned["id"]


def drain_tunnel_output(pipe, output):
    # cloudflared logs go only to memory, never to tracked files.
    try:
        for line in iter(pipe.readline, ""):
            match = URL_PATTERN.search(line)
            if match:
                output.put(match.group())
    finally:
        pipe.close()


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main():
    tunnel_binary = require_explicit_opt_in(os.environ)
    port = choose_port()
    credentials = {
        "passenger": secrets.token_urlsafe(36),
        "pilot": secrets.token_urlsafe(36),
        "dispatcher": secrets.token_urlsafe(36),
    }
    server = tunnel = None
    with tempfile.TemporaryDirectory(prefix="pd-demo-sync-") as temp:
        env = dict(os.environ)
        env.update({
            "PD_DEMO_ISOLATED": "YES",
            "PD_DEMO_HOST": "127.0.0.1",
            "PD_DEMO_PORT": str(port),
            "PD_DEMO_DB": str(Path(temp) / "synthetic.sqlite"),
            "PD_DEMO_BROWSER_ORIGIN": SAFARI_PREVIEW_ORIGIN,
        })
        for role, token in credentials.items():
            env[f"PD_DEMO_{role.upper()}_TOKEN"] = token
        try:
            server = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve().parent / "pd_demo_server.py")],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_for_server(port, credentials["passenger"], server)
            synthetic_trip_id = seed_synthetic_chat_trip(port, credentials)
            tunnel = subprocess.Popen(
                [tunnel_binary, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )
            output = queue.Queue()
            threading.Thread(
                target=drain_tunnel_output,
                args=(tunnel.stderr, output), daemon=True,
            ).start()
            try:
                address = output.get(timeout=35)
            except queue.Empty as exc:
                raise RuntimeError("No Quick Tunnel URL received; check cloudflared installation/network") from exc
            if tunnel.poll() is not None:
                raise RuntimeError("Quick Tunnel exited during startup")
            print("\nPRIVATE DRIVE — temporary isolated demo (NOT PRODUCTION)")
            print("Expires automatically after 20 minutes, or stop with Ctrl+C.")
            print("HTTPS URL:", address)
            print("Synthetic assigned trip ID:", synthetic_trip_id[:8] + "…")
            for role, token in credentials.items():
                print(role.upper() + " TEST TOKEN:", token)
            print("Keep URL and role tokens private. Never use production details.")
            print("Allowed Safari origin:", SAFARI_PREVIEW_ORIGIN)
            print("iPHONE SAFARI: open", SAFARI_PREVIEW_ORIGIN)
            print("  enter HTTPS URL and PASSENGER TEST TOKEN, then connect.")
            print("A public HTTPS tunnel does not authenticate users: use dummy data only.")
            print("ANDROID PILOT: use the already installed demo APK's isolated test chat.")
            print("PHONE A (PASSENGER): open passenger cabin -> test chat,")
            print("  enter HTTPS URL and PASSENGER TEST TOKEN, then connect.")
            print("PHONE B (PILOT): open pilot cabin -> left menu -> test chat,")
            print("  enter the same HTTPS URL and PILOT TEST TOKEN, then connect.")
            print("The same synthetic assigned trip should appear in both chats.")
            print("Send a made-up message A -> B, then reply B -> A.")
            print("Never enter personal addresses, real orders or real payment data.")
            print("No manual trip creation or pilot assignment is needed.")
            print("Safari Web needs no iOS installation. It cannot view production trips.")
            print("All data and local SQLite are deleted when this process exits.\n")
            sys.stdout.flush()
            deadline = time.monotonic() + MAX_SECONDS
            while time.monotonic() < deadline:
                if tunnel.poll() is not None or server.poll() is not None:
                    raise RuntimeError("Temporary demo server or tunnel stopped unexpectedly")
                time.sleep(1)
        finally:
            stop(tunnel)
            stop(server)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTemporary tunnel stopped; synthetic database removed.")
    except RuntimeError as exc:
        print("TEST ONLY ERROR:", exc, file=sys.stderr)
        sys.exit(1)
