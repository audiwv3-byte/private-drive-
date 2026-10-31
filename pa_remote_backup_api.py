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
    # A copied API-token string may include line wraps or an HTTP "Token " prefix.
    # Normalize formatting only; never print or persist the credential.
    token = re.sub(r"^Token\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I)
    token = "".join(token.split())
    console = os.environ.get("PA_CONSOLE_ID", "").strip()
    if not token:
        raise RuntimeError("GitHub secret PA_API_TOKEN has not been configured")
    if not re.fullmatch(r"[0-9]{1,12}", console):
        raise RuntimeError("PA_CONSOLE_ID must be a numeric Bash console ID")
    prefix = f"https://{PA_HOST}/api/v0/user/{PA_USER}"
    session = requests.Session()
    # Validate credentials with the documented lightweight endpoint first.
    # Never print the token, request header, or server response body.
    session.headers.update({"Authorization": "Token " + token})
    probe = session.get(prefix + "/cpu/", timeout=35)
    if probe.status_code == 401:
        # PythonAnywhere hosts US and EU accounts on separate official API servers.
        # Probe the EU host read-only; neither endpoint receives application data.
        eu_probe = session.get("https://eu.pythonanywhere.com/api/v0/user/" + PA_USER + "/cpu/", timeout=35)
        if eu_probe.status_code == 200:
            raise RuntimeError("Token is valid on PythonAnywhere EU, but the live site is configured for the US host; no backup was attempted")
        raise RuntimeError(
            "PythonAnywhere auth rejected on both official hosts: US HTTP 401, EU HTTP "
            + str(eu_probe.status_code)
            + ". Check GitHub secret PA_API_TOKEN against the live account."
        )
    if probe.status_code != 200:
        raise RuntimeError(f"PythonAnywhere API probe failed: HTTP {probe.status_code}")
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
    status_path = "/home/wilsonpark/pd_backup_status_" + nonce + ".txt"
    log_path = "/home/wilsonpark/pd_backup_log_" + nonce + ".txt"
    # Never depend on the browser console's rolling 500-character buffer.
    # Shell writes a private status file even if the backup utility fails.
    command = (
        "umask 077; python3 " + RUNNER + " --root " + PROJECT
        + " --backup > " + log_path
        + " 2>&1; status=$?; if [ \"$status\" -eq 0 ]; "
        + "then printf 'OK\\n' > " + status_path
        + "; else printf 'FAILED\\n' > " + status_path + "; fi"
    )
    api("POST", "/consoles/" + console + "/send_input/", data={"input": command + "\n"})
    print("Backup command submitted; waiting for private status file...")
    status = ""
    for _ in range(24):
        time.sleep(5)
        response = session.get(prefix + "/files/path" + status_path, timeout=35)
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            raise RuntimeError("Backup status check failed: HTTP " + str(response.status_code))
        status = response.text.strip()
        break
    if status != "OK":
        if status == "FAILED":
            raise RuntimeError("Remote backup failed. Review private PythonAnywhere log: " + log_path)
        raise RuntimeError("No verified completion status from remote console; source files unchanged")
    log = api("GET", "/files/path" + log_path).text
    pattern = re.compile(r"BACKUP_VERIFIED\s+(/home/wilsonpark/private_drive_backups/snapshot_[A-Za-z0-9_]+)")
    match = pattern.search(log)
    if not match:
        raise RuntimeError("Remote script reported OK but no snapshot path was found")
    snapshot = match.group(1)
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
