"""Issue #30: offline-only release readiness primitives.

NO remote API, network, deployment, writes to a production path or CLI.
Used by synthetic tests to verify backup integrity, migration atomicity,
dependency checks and safe rollback behavior.
"""
import hashlib
import importlib
import os
import sqlite3
from pathlib import Path

REQUIRED_MODULES = (
    "pd_document_review",
    "pd_issue30_stage_adapter",
    "pd_issue30_decision_bridge",
    "pd_issue30_document_storage_guard",
    "pd_issue30_patch_live_onboarding_offline",
    "pd_issue30_patch_live_dispatcher_offline",
)
EXPECTED_SOURCE_SHA = "7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b"


class ReleaseBlocked(RuntimeError):
    pass


def check_dependencies():
    for name in REQUIRED_MODULES:
        module = importlib.import_module(name)
        if not getattr(module, "__file__", "").endswith(name + ".py"):
            raise ReleaseBlocked("Unexpected dependency module: " + name)
    return True


def verify_source_sha(content):
    if type(content) is not bytes or hashlib.sha256(content).hexdigest() != EXPECTED_SOURCE_SHA:
        raise ReleaseBlocked("Deployed source SHA changed: STOP")
    return True


def backup_sqlite(src_conn, destination):
    """For tests only: SQLite backup API ensures internally consistent snapshot.

    Caller must provide isolated *destination* not already existing. The
    production runbook prohibits direct file copy of live WAL databases.
    """
    target = Path(destination)
    if target.exists():
        raise ReleaseBlocked("Never overwrite an existing backup")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src_conn.backup(dst)
            dst.execute("PRAGMA quick_check")
            check = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise ReleaseBlocked("Backup integrity check failed")
        finally:
            dst.close()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        with sqlite3.connect(str(target)) as verify:
            if verify.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ReleaseBlocked("Backup readback failed")
        return digest
    except BaseException:
        if target.exists():
            target.unlink()
        raise


def migrate_synthetic(conn):
    """Synthetic-only migration, with transaction-owned two-table creation."""
    import pd_document_review as reviews
    import pd_issue30_document_storage_guard as guard
    if not conn.in_transaction:
        raise ReleaseBlocked("Migrations require caller-owned BEGIN IMMEDIATE")
    reviews.ensure_tables(conn)
    guard.ensure_tables(conn)
    required = {"pd_document_reviews", "pd_document_review_events", "pd_document_replacements"}
    found = {x[0] for x in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pd_document_%'"
    )}
    if not required.issubset(found):
        raise ReleaseBlocked("Incomplete migration")
    return True


def verify_restore_copy(backup, restored_path, expected_digest):
    """Offline copy/readback into isolated path, never into production."""
    source, target = Path(backup), Path(restored_path)
    if target.exists():
        raise ReleaseBlocked("Restoration must never overwrite an existing database")
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected_digest:
        raise ReleaseBlocked("Backup SHA-256 changed")
    target.write_bytes(source.read_bytes())
    with sqlite3.connect(str(target)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ReleaseBlocked("Restored SQLite integrity invalid")
    return True
