"""Manual-only PRIVATE DRIVE remote backup through the official PythonAnywhere API.

Requires a GitHub Actions secret PA_API_TOKEN. Never downloads or publishes user
databases; SQLite snapshots are taken consistently on the PythonAnywhere host.
No production application files are changed, and no webapp reload occurs.
"""
import hashlib
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

import requests

PA_USER = "wilsonpark"
PA_HOST = "www.pythonanywhere.com"
PROJECT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
RUNNER = "/home/wilsonpark/pd_safe_backup_runner_20261031.py"
FILES = (
    "miniapp/templates/index.html",
    "miniapp_server.py",
    "pd_tips_widget.js",
    "pd_tips_widget.py",
    "Euro_Baltic_Transfer.py",
)


def main():
    token = os.environ.get("PA_API_TOKEN", "").strip()
    console = os.environ.get("PA_CONSOLE_ID", "").strip()
    if not token:
        raise RuntimeError("GitHub secret PA_API_TOKEN has not been configured")
    if not re.fullmatch(r"[0-9]{1,12}", console):
        raise RuntimeError("PA_CONSOLE_ID must be a numeric Bash console ID")
    prefix = f"https://{PA_HOST}/api/v0/user/{PA_USER}"
    session = requests.Session()
    session.headers.update({"Authorization": "Token " + token})
    def api(method, endpoint, **kwargs):
        response = session.request(method, prefix + endpoint, timeout=35, **kwargs)
        if not response.ok:
            raise RuntimeError(f"PythonAnywhere API failed: {method} {endpoint.split('?')[0]} status {response.status_code}")
        return response
    print("Checking production source fingerprints (source contents not printed)...")
    for relative in FILES:
        response = api("GET", "/files/path" + PROJECT + "/" + relative)
        data = response.content
        if len(data) < 100:
            raise RuntimeError("Unexpected empty production source: " + relative)
        print(relative, "bytes", len(data), "sha256", hashlib.sha256(data).hexdigest()[:16])
    current = api("GET", "/consoles/" + console + "/").json()
    if not str(current.get("id", console)) == console:
        raise RuntimeError("Console identity check failed")
    print("Bash console exists, uploading verified backup runner outside web root...")
    contents = Path(__file__).with_name("pd_safe_backup.py").read_bytes()
    try:
        existing = session.get(prefix + "/files/path" + RUNNER, timeout=35)
        if existing.status_code == 200:
            if existing.content != contents:
                raise RuntimeError("Remote runner already exists with different content; refusing overwrite")
        elif existing.status_code == 404:
            api("POST", "/files/path" + RUNNER,
                files={"content": ("pd_safe_backup_runner.py", contents, "text/x-python")})
        else:
            raise RuntimeError("Could not verify remote runner status " + str(existing.status_code))
    finally:
        pass
    nonce = secrets.token_hex(8)
    command = "echo PD_BACKUP_START_" + nonce + " && python " + RUNNER + " --root " + PROJECT + " --backup"
    api("POST", "/consoles/" + console + "/send_input/", data={"input": command + "\n"})
    print("Backup command submitted; checking PythonAnywhere console output...")
    start_seen = False
    pattern = re.compile(r"BACKUP_VERIFIED\s+(/home/wilsonpark/private_drive_backups/snapshot_[A-Za-z0-9_]+)")
    snapshot = None
    for _ in range(18):
        time.sleep(5)
        result = api("GET", "/consoles/" + console + "/get_latest_output/")
        output = result.text
        try:
            payload = result.json()
            if isinstance(payload, dict):
                output = str(payload.get("output", payload))
        except ValueError:
            pass
        start_seen = start_seen or "PD_BACKUP_START_" + nonce in output
        match = pattern.search(output)
        if start_seen and match:
            snapshot = match.group(1)
            break
    if not snapshot:
        raise RuntimeError("Backup confirmation not received; remote source files were not altered")
    manifest_resp = api("GET", "/files/path" + snapshot + "/MANIFEST.json")
    manifest = manifest_resp.json()
    names = manifest.get("files", {})
    if not all(name in names for name in FILES + ("orders.db", "users.db")):
        raise RuntimeError("Backup manifest is missing required production files or databases")
    print("BACKUP_VERIFIED", snapshot, "files", len(names))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BACKUP_FAILED:", str(exc), file=sys.stderr)
        raise SystemExit(1)
