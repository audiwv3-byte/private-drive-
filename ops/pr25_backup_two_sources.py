"""PR25 production source backup only: reads 2 pinned files and writes 2 private copies.
No production source, database, webapp, order, payment or runtime modifications.
"""
import hashlib
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone

USER = "wilsonpark"
API = "https://www.pythonanywhere.com/api/v0/user/" + USER + "/files/path"
SOURCE = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
BACKUPS = "/home/wilsonpark/private_drive_backups/"
PINNED = {
    "miniapp_server.py": "e827dcc675c40195fc01eccaf72ee081472b7a00a0b92e8a814f09711bf04959",
    "pd_trip_runtime_v4.py": "0bee9f529e34000d38f8f09cf76c909aa27d073fabb191ea9e468ce3ba1add62",
}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def send(path, token, method="GET", data=None, ctype=None):
    headers = {"Authorization": "Token " + token, "User-Agent": "PD-PR25-backup/1"}
    if ctype:
        headers["Content-Type"] = ctype
    request = urllib.request.Request(API + path, method=method, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=55) as response:
        return response.status, response.read(2_000_001)

def upload(path, data, token):
    boundary = "pdpr25" + secrets.token_hex(12)
    header = ('--' + boundary + '\r\nContent-Disposition: form-data; name="content"; filename="'
              + path.rsplit('/', 1)[-1] + '"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    body = header + data + ('\r\n--' + boundary + '--\r\n').encode()
    return send(path, token, "POST", body, "multipart/form-data; boundary=" + boundary)

def main():
    token = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    if token.lower().startswith("token "):
        token = token[6:].strip()
    if not token:
        raise RuntimeError("API_TOKEN_MISSING")
    # Verify backup parent exists. No mkdir API calls.
    status, _ = send(BACKUPS, token)
    if status != 200:
        raise RuntimeError("BACKUP_DIRECTORY_UNAVAILABLE")
    originals = {}
    for name, expected in PINNED.items():
        status, data = send(SOURCE + name, token)
        if status != 200 or digest(data) != expected:
            raise RuntimeError("SOURCE_CHANGED_ABORT_" + name)
        originals[name] = data
        print("SOURCE_PINNED_OK", name, expected, flush=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + secrets.token_hex(4)
    for name, data in originals.items():
        backup = BACKUPS + "pr25_predeploy_" + suffix + "__original__" + name
        # Fail if a collision somehow occurs; never overwrite a prior backup.
        try:
            send(backup, token)
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
        else:
            raise RuntimeError("BACKUP_COLLISION_ABORT")
        upload(backup, data, token)
        _, recovered = send(backup, token)
        if recovered != data or digest(recovered) != PINNED[name]:
            raise RuntimeError("BACKUP_READBACK_FAILED_" + name)
        print("BACKUP_VERIFIED", backup, "SHA256", digest(recovered), "BYTES", len(recovered), flush=True)
    # Recheck after backup; application code must remain unchanged.
    for name, data in originals.items():
        _, current = send(SOURCE + name, token)
        if current != data:
            raise RuntimeError("LIVE_SOURCE_CHANGED_DURING_BACKUP_" + name)
    print("PR25_TWO_SOURCE_BACKUPS_VERIFIED_NO_PRODUCTION_SOURCE_CHANGES", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("PR25_BACKUP_BLOCKED", type(error).__name__, str(error)[:120], flush=True)
        raise SystemExit(1)
