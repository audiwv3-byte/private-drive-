"""Surgical production patch with verified snapshot, exact fingerprints and rollback.

Run only from the restricted GitHub Actions workflow using PA_API_TOKEN.
Never copies production source, customer data or credentials into CI logs.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time

import requests

HOST = "https://www.pythonanywhere.com"
USER = "wilsonpark"
ROOT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
SNAPSHOT = "/home/wilsonpark/private_drive_backups/snapshot_20261106T074103Z_252aee"
SITE = "https://wilsonpark.pythonanywhere.com/"
BASE = f"{HOST}/api/v0/user/{USER}"
TARGETS = {
    "pd_fixed_prices.py": {
        "bytes": 735,
        "sha16": "60ac40a4e70f256c",
        "old": b"return '190.00' if data.get('roundtrip') else '130.00'",
        "new": b"return '200.00' if data.get('roundtrip') else '130.00'",
    },
    "pd_pilot_cabinet_v4.js": {
        "bytes": 15671,
        "sha16": "26307f627ea09de6",
        "old": b"passenger.classList.toggle('hidden',!user.registered);",
        "new": b"passenger.classList.add('hidden');",
    },
    "pd_trip_runtime_v4.js": {
        "bytes": 21270,
        "sha16": "5edf151f714eefe4",
        "old": b"function cleanDialog(){if(map)map.remove();",
        "new": b"function cleanDialog(){stopPosition();closing(false);if(map)map.remove();",
    },
}

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main():
    token = "".join(re.sub(r"^Token\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I).split())
    if not token:
        raise RuntimeError("Missing configured PA_API_TOKEN")
    session = requests.Session()
    session.headers["Authorization"] = "Token " + token

    def get_api(path):
        r = session.get(BASE + path, timeout=40)
        if r.status_code != 200:
            raise RuntimeError(f"PythonAnywhere GET failed: HTTP {r.status_code}")
        return r.content

    def put_api(path, payload):
        r = session.post(
            BASE + path,
            files={"content": ("approved-patch.txt", payload, "application/octet-stream")},
            timeout=40,
        )
        if r.status_code != 200:
            raise RuntimeError(f"PythonAnywhere overwrite rejected: HTTP {r.status_code}")

    def reload_webapp():
        r = session.post(BASE + "/webapps/wilsonpark.pythonanywhere.com/reload/", timeout=60)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"Webapp reload failed: HTTP {r.status_code}")

    def live_path(name):
        return "/files/path" + ROOT + "/" + name

    def check_health():
        for _ in range(8):
            try:
                r = requests.get(SITE, timeout=15, headers={"Cache-Control": "no-cache"})
                if r.status_code == 200 and ("privatdrive" in r.text.lower() or "private drive" in r.text.lower()):
                    return
            except requests.RequestException:
                pass
            time.sleep(3)
        raise RuntimeError("Website did not pass health check")

    # Never write unless independently verified backup exists and matches every live target.
    print("PATCH_PREFLIGHT: verifying snapshots and unchanged production fingerprints")
    original, patched = {}, {}
    for name, item in TARGETS.items():
        source = get_api(live_path(name))
        backup = get_api("/files/path" + SNAPSHOT + "/" + name)
        if source != backup:
            raise RuntimeError("PRODUCTION_CHANGED_SINCE_BACKUP: " + name)
        if len(source) != item["bytes"] or digest(source)[:16] != item["sha16"]:
            raise RuntimeError("PRODUCTION_FINGERPRINT_MISMATCH: " + name)
        if source.count(item["old"]) != 1 or item["new"] in source:
            raise RuntimeError("PATCH_ANCHOR_MISMATCH: " + name)
        out = source.replace(item["old"], item["new"], 1)
        if out == source or out.count(item["new"]) != 1:
            raise RuntimeError("PATCH_VALIDATION_FAILED: " + name)
        original[name] = source
        patched[name] = out
        print("PATCH_READY", name, "before", digest(source)[:16], "after", digest(out)[:16])
    print("SNAPSHOT_VERIFIED: all three files match independent backup")

    check_health()
    written = []
    try:
        for name in TARGETS:
            # Optimistic concurrency check before each write.
            now = get_api(live_path(name))
            if now != original[name]:
                raise RuntimeError("CONCURRENT_CHANGE_DETECTED: " + name)
            put_api(live_path(name), patched[name])
            written.append(name)
            if get_api(live_path(name)) != patched[name]:
                raise RuntimeError("WRITE_VERIFICATION_FAILED: " + name)
            print("PATCH_WRITTEN_VERIFIED", name)
        reload_webapp()
        print("RELOAD_OK")
        check_health()
        # Verify served JavaScript really uses patched source.
        for name, url in (
            ("pd_pilot_cabinet_v4.js", SITE + "assets/pd-pilot-cabinet-v4.js"),
            ("pd_trip_runtime_v4.js", SITE + "assets/pd-trip-runtime-v4.js"),
        ):
            response = requests.get(url, timeout=30, headers={"Cache-Control": "no-cache"})
            if response.status_code != 200 or TARGETS[name]["new"] not in response.content:
                raise RuntimeError("PUBLIC_ASSET_NOT_UPDATED: " + name)
            print("ASSET_VERIFIED", name)
        for name in TARGETS:
            if get_api(live_path(name)) != patched[name]:
                raise RuntimeError("FINAL_SOURCE_CHANGED: " + name)
        print("PATCH_PRODUCTION_SUCCESS: three targeted files, health and public assets verified")
    except Exception as error:
        print("PATCH_PRODUCTION_FAILED, initiating rollback:", str(error), file=sys.stderr)
        rollback_failed = []
        for name in reversed(written):
            try:
                current = get_api(live_path(name))
                if current != patched[name]:
                    raise RuntimeError("Current file modified by another writer; not overwriting")
                put_api(live_path(name), original[name])
                if get_api(live_path(name)) != original[name]:
                    raise RuntimeError("Rollback readback mismatch")
                print("ROLLBACK_VERIFIED", name)
            except Exception as rollback_error:
                rollback_failed.append(name)
                print("ROLLBACK_ERROR", name, str(rollback_error), file=sys.stderr)
        if written:
            try:
                reload_webapp()
                check_health()
                print("ROLLBACK_RELOAD_HEALTH_OK")
            except Exception as reload_error:
                print("ROLLBACK_RELOAD_FAILED", str(reload_error), file=sys.stderr)
                rollback_failed.append("webapp")
        if rollback_failed:
            raise RuntimeError("ROLLBACK_INCOMPLETE: " + ",".join(rollback_failed)) from error
        raise RuntimeError("PATCH_ABORTED_AND_ROLLED_BACK") from error

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PATCH_ERROR:", str(exc), file=sys.stderr)
        sys.exit(1)
