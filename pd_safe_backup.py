"""Read-only audit and isolated recovery snapshot for PRIVATE DRIVE.

No payment, order or application configuration is modified.
The backup stays in the PythonAnywhere account home directory, not in the web root.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone

REQUIRED = (
    "Euro_Baltic_Transfer.py",
    "miniapp_server.py",
    "miniapp/templates/index.html",
    "pd_tips_widget.js",
    "pd_tips_widget.py",
)
DATABASES = ("orders.db", "users.db")
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".yml"}
EXCLUDED_FOLDERS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "backups"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_files(root):
    files = []
    for path in list(root.iterdir()) + list((root / "miniapp").rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_FOLDERS or part.startswith(".") for part in rel.parts):
            continue
        files.append(rel)
    return sorted(set(files), key=str)


def check_inputs(root):
    for relative in REQUIRED:
        file = root / relative
        if not file.is_file() or file.is_symlink() or file.stat().st_size < 20:
            raise RuntimeError("Required source missing or empty: " + relative)
    for name in DATABASES:
        file = root / name
        if not file.is_file() or file.is_symlink():
            raise RuntimeError("Required production database missing: " + name)


def quick_check(dbfile):
    connection = sqlite3.connect(dbfile.as_uri() + "?mode=ro", uri=True)
    try:
        value = connection.execute("PRAGMA quick_check").fetchone()[0]
        if value != "ok":
            raise RuntimeError("SQLite integrity check failed for " + dbfile.name)
    finally:
        connection.close()


def make_backup(root, destination_root):
    root, destination_root = root.resolve(), destination_root.expanduser().resolve()
    if destination_root == root or root in destination_root.parents:
        raise ValueError("Backups must be stored outside the application directory")
    check_inputs(root)
    paths = source_files(root)
    for name in DATABASES:
        quick_check(root / name)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination_root.chmod(0o700)
    snapshot = destination_root / ("snapshot_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3))
    snapshot.mkdir(mode=0o700)
    info = {"created_utc": datetime.now(timezone.utc).isoformat(), "source": str(root), "files": {}}
    for rel in paths:
        source, target = root / rel, snapshot / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.parent.chmod(0o700)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        original_hash = digest(source)
        if digest(target) != original_hash:
            raise RuntimeError("Source copy mismatch: " + str(rel))
        info["files"][str(rel)] = {"sha256": original_hash, "bytes": target.stat().st_size}
    for name in DATABASES:
        source, target = root / name, snapshot / name
        source_db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            with sqlite3.connect(target) as target_db:
                source_db.backup(target_db)
        finally:
            source_db.close()
        target.chmod(0o600)
        quick_check(target)
        info["files"][name] = {"sha256": digest(target), "bytes": target.stat().st_size, "sqlite": True}
    manifest = snapshot / "MANIFEST.json"
    manifest.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.chmod(0o600)
    verify_backup(snapshot)
    return snapshot


def verify_backup(snapshot):
    manifest = json.loads((snapshot / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, details in manifest["files"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid manifest path")
        file = snapshot / name
        if not file.is_file() or digest(file) != details["sha256"] or file.stat().st_size != details["bytes"]:
            raise RuntimeError("Backup verification failed: " + name)
        if details.get("sqlite"):
            quick_check(file)
    return len(manifest["files"])


def main():
    parser = argparse.ArgumentParser(description="PRIVATE DRIVE safe audit and isolated backup")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--backup", action="store_true", help="Create snapshot including consistent SQLite backups")
    parser.add_argument("--destination", type=Path, default=Path.home() / "private_drive_backups")
    parser.add_argument("--verify", type=Path, help="Verify an existing backup snapshot")
    args = parser.parse_args()
    if args.verify:
        print("BACKUP_VERIFIED files=" + str(verify_backup(args.verify.resolve())))
        return
    root = args.root.resolve()
    check_inputs(root)
    files = source_files(root)
    for name in DATABASES:
        quick_check(root / name)
    print("AUDIT_OK sources=" + str(len(files)) + " databases=2")
    if args.backup:
        result = make_backup(root, args.destination)
        print("BACKUP_VERIFIED " + str(result))


if __name__ == "__main__":
    main()
