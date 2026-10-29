"""PRIVATE DRIVE guarded production update. Never publish this script's backups.
Usage (from staging): python pd_release_safeguard.py audit|backup|install|status
"""
from __future__ import annotations
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
from urllib.parse import quote

STAGE = pathlib.Path(__file__).resolve().parent
LIVE = pathlib.Path("/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18")
SAFE = pathlib.Path("/home/wilsonpark/pd_secure_backups")
WSGI = pathlib.Path("/var/www/wilsonpark_pythonanywhere_com_wsgi.py")
BACKUP_MARKER = STAGE / "pd_release_backup_path_20261029.txt"
BASE = {
    "miniapp/templates/index.html": "625ded6baa041f8597bb9988739088469e8e5538",
    "pd_pilot_cabinet_v4.js": "b5073c4cfae9404315aafe094617f91531d0ad2e",
    "pd_tips_widget.js": "bd3c54c5211e939fce30b8ed38d9afb4bf62d1c8",
    "pd_tips_widget.py": "82c9f43edddb8f710ed19ea98dc5e1434df1f81c",
    "pd_trip_runtime_v4.js": "f05578288b9c8bc43fd0f850e9b3488d22ac4305",
    "pd_trip_runtime_v4.py": "dc59de8c0ea3f503ef4f6efd2ecc3e8a780ad066",
    "miniapp/static/pd-pilot-fullscreen-v5.js": None
}
NEW = {
    "miniapp/static/pd-pilot-fullscreen-v5.js": "0b0c0d72c9ef4080512d323857e3be2c2a93594b",
    "miniapp/templates/index.html": "b1075774a7752d2728881b7daccb5ea3761a4c4e",
    "pd_pilot_cabinet_v4.js": "c8a81cc68e4d4223156ac8ac2546a024013de340",
    "pd_tips_widget.js": "52d310629ccf4928b3899472e12c466d1b7f82dd",
    "pd_tips_widget.py": "daec3d2b1fed1bd02181b3e1327f6b4dd4dea79c",
    "pd_trip_runtime_v4.js": "ab59559781927ae3d6b51e6120935cfe5fd4e76b",
    "pd_trip_runtime_v4.py": "619c403f79358b43b7086e75ffb979fabf3183cc"
}
def blob(path):
    if not path.is_file():
        return None
    raw = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()

def check(expected_live=BASE):
    issues = []
    for rel in BASE:
        source = STAGE / rel
        actual_staged = blob(source)
        actual_live = blob(LIVE / rel)
        expected_before = expected_live[rel]
        if actual_staged != NEW[rel]:
            issues.append(f"STAGE_MISMATCH {rel} {actual_staged}")
        if actual_live != expected_before:
            issues.append(f"LIVE_DRIFT {rel} live={actual_live} baseline={expected_before}")
        print(f"{rel} | live={str(actual_live)[:12]} | base={str(expected_before)[:12]} | stage={str(actual_staged)[:12]} | {'OK' if actual_staged==NEW[rel] and actual_live==expected_before else 'CHECK'}")
    if not WSGI.is_file():
        issues.append("WSGI_NOT_FOUND")
    if STAGE == LIVE or not (LIVE / "miniapp_server.py").is_file():
        issues.append("WRONG_PRODUCTION_DIR")
    if issues:
        print("ABORT: " + "; ".join(issues))
        return False
    print("AUDIT PASS: release content matches GitHub and existing live files match reviewed baseline")
    return True

def db_snapshot(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = "file:" + quote(str(source)) + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=20) as src:
        with sqlite3.connect(str(target), timeout=20) as dst:
            src.backup(dst)
            checkrow = dst.execute("PRAGMA quick_check").fetchone()
            if not checkrow or checkrow[0] != "ok":
                raise RuntimeError("SQLite integrity check failed for " + source.name)
    os.chmod(target, 0o600)

def latest_backup():
    if not BACKUP_MARKER.is_file():
        raise RuntimeError("Backup marker missing; refuse install")
    target = pathlib.Path(BACKUP_MARKER.read_text().strip())
    if target.parent != SAFE or not (target / "READY").is_file():
        raise RuntimeError("Backup incomplete or unexpected location")
    return target

def backup():
    if not check():
        raise RuntimeError("Existing live files diverged; manual reconciliation required")
    SAFE.mkdir(parents=True, exist_ok=True)
    os.chmod(SAFE, 0o700)
    dest = SAFE / ("PRIVATE_DRIVE_PREDEPLOY_20261029_" + time.strftime("%H%M%S"))
    dest.mkdir(mode=0o700, exist_ok=False)
    print("BACKUP_DIR=" + str(dest), flush=True)
    for rel in BASE:
        src = LIVE / rel
        if src.is_file():
            dst = dest / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if WSGI.exists():
        shutil.copy2(WSGI, dest / "wsgi.py.saved")
    if (LIVE / ".env").is_file():
        shutil.copy2(LIVE / ".env", dest / "env.saved")
        os.chmod(dest / "env.saved", 0o600)
    # Consistent SQLite snapshots. Include app-local DBs and top-level orders/users DBs.
    seen = set()
    all_databases = list(LIVE.rglob("*.db"))
    all_databases += [pathlib.Path("/home/wilsonpark") / n for n in ("orders.db","users.db")]
    for source in all_databases:
        if not source.is_file() or source in seen:
            continue
        seen.add(source)
        if any(x in source.parts for x in (".git", "release_backups", "__pycache__")):
            continue
        try:
            relative = source.relative_to(LIVE)
            dbdir = dest / "databases" / "app"
        except ValueError:
            relative = pathlib.Path(source.name)
            dbdir = dest / "databases" / "home"
        db_snapshot(source, dbdir / relative)
        print("SNAPSHOT_DB " + source.name, flush=True)
    if not any((dest / "databases").rglob("*.db")):
        raise RuntimeError("No SQLite databases found; refuse install")
    # Full source-code snapshot, excludes live DBs and config secret stored separately.
    with tarfile.open(dest / "production_code.tar.gz", "w:gz") as archive:
        def filter_member(info):
            parts = pathlib.PurePosixPath(info.name).parts
            if any(part in (".git","__pycache__", "release_backups", "pd_secure_backups") or part.startswith("backup_") for part in parts):
                return None
            name = pathlib.PurePosixPath(info.name).name
            if name == ".env" or name.endswith(".db") or ".db-" in name:
                return None
            return info
        archive.add(LIVE, arcname="PRIVATE_DRIVE_MiniApp_2026_10_18", filter=filter_member, recursive=True)
    summary = {"timestamp":time.strftime("%Y-%m-%d %H:%M:%S"), "baseline":BASE, "target":NEW, "db_count":len(seen)}
    (dest / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (dest / "READY").write_text("PREDEPLOY_BACKUP_VALID\n")
    BACKUP_MARKER.write_text(str(dest))
    print("BACKUP PASS: all code, config, and database snapshots captured; live site untouched", flush=True)

def atomic_copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".pd-install-", dir=dst.parent)
    os.close(fd)
    try:
        shutil.copy2(src, temp_name)
        os.replace(temp_name, dst)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

def install():
    folder = latest_backup()
    if not check():
        raise RuntimeError("Refusing deployment: current live or staged files changed since audit")
    touched = []
    try:
        for rel in BASE:
            atomic_copy(STAGE / rel, LIVE / rel)
            touched.append(rel)
            if blob(LIVE / rel) != NEW[rel]:
                raise RuntimeError("Verification failed after copy: " + rel)
        for rel in BASE:
            if rel.endswith(".py"):
                compile((LIVE / rel).read_bytes(), rel, "exec")
        (folder / "INSTALLED").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        print("INSTALL PASS: seven reviewed files copied and verified. WSGI reload still required.", flush=True)
    except BaseException:
        print("INSTALL ERROR: rolling back changed code files without restoring DBs", flush=True)
        for rel in reversed(touched):
            saved = folder / "files" / rel
            if saved.exists():
                atomic_copy(saved, LIVE / rel)
            elif (LIVE / rel).exists():
                (LIVE / rel).unlink()
        raise

def status():
    print("STATUS: backup=" + (BACKUP_MARKER.read_text().strip() if BACKUP_MARKER.exists() else "NONE"))
    for rel in BASE:
        found = blob(LIVE / rel)
        print(rel, "RELEASE" if found == NEW[rel] else "BASE" if found == BASE[rel] else "DRIFT", found)

if __name__ == "__main__":
    try:
        action = sys.argv[1] if len(sys.argv)>1 else ""
        if action == "audit":
            raise SystemExit(0 if check() else 2)
        elif action == "backup": backup()
        elif action == "install": install()
        elif action == "status": status()
        else: raise RuntimeError("Usage: audit | backup | install | status")
    except Exception as exc:
        print("SAFEGUARD ERROR:", type(exc).__name__, str(exc), flush=True)
        raise SystemExit(3)
