"""Issue #30 — OFFLINE-only document storage guard.

No routes registered and no live integration. Call functions only inside the
existing caller-owned BEGIN IMMEDIATE transaction. The caller validates file
format, size and image safety using deployed read_photos() BEFORE these calls.
No method begins/commits a transaction or grants a pilot role.
"""
import hashlib
import re
from datetime import datetime, timezone

import pd_document_review as review


class DocumentStorageError(review.ReviewError):
    pass


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _check_bytes(content):
    if not isinstance(content, bytes) or not content:
        raise DocumentStorageError("Document must be nonempty validated JPEG bytes")


def _check_id(value):
    if type(value) is not int or value < 1:
        raise DocumentStorageError("Invalid applicant identity")


def _check_side(side):
    if side not in review.SIDES:
        raise DocumentStorageError("Unknown document side")


def _check_lease(sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise DocumentStorageError("Refresh document SHA before replacement")


def _transaction(conn):
    if not conn.in_transaction:
        raise DocumentStorageError("BEGIN IMMEDIATE transaction required")


def _schema(conn, require_audit=False):
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('pd_driver_applications','pd_driver_documents',"
        "'pd_document_reviews','pd_document_review_events',"
        "'pd_document_replacements')"
    )}
    required = {"pd_driver_applications", "pd_driver_documents"}
    if require_audit:
        required |= {"pd_document_reviews", "pd_document_review_events",
                     "pd_document_replacements"}
    if not required.issubset(names):
        raise DocumentStorageError("Required tables are not installed")


def ensure_tables(conn):
    """Explicit, offline-only migration to be tested separately before deployment."""
    conn.execute("""CREATE TABLE IF NOT EXISTS pd_document_replacements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        side TEXT NOT NULL,
        actor_id INTEGER NOT NULL,
        previous_sha256 TEXT NOT NULL,
        replacement_sha256 TEXT NOT NULL,
        replaced_at TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action='dispatcher_replace')
    )""")


def _app(conn, applicant):
    row = conn.execute(
        "SELECT status,stage FROM pd_driver_applications WHERE telegram_id=?",
        (applicant,),
    ).fetchone()
    if row is None:
        raise DocumentStorageError("Pilot application not found")
    return row[0], row[1]


def pilot_insert_missing(conn, *, applicant, side, image):
    """Pilot may add only never-stored side, without UPSERT/REPLACE.

    Must be called for EACH supplied file; never retain old live UPSERT for
    even one upload path. Stage1 -> FIRST; stage2 -> SECOND only.
    """
    _transaction(conn)
    _check_id(applicant)
    _check_side(side)
    _check_bytes(image)
    _schema(conn)
    status, stage = _app(conn, applicant)
    if status == "pending" and stage == 1:
        allowed = review.FIRST
    elif stage == 2 and status in ("stage2", "pending"):
        allowed = review.SECOND
    else:
        raise DocumentStorageError("Registration stage does not permit upload")
    if side not in allowed:
        raise DocumentStorageError("Document type is not allowed in current stage")
    # Atomic uniqueness enforcement; never update an existing BLOB.
    result = conn.execute(
        "INSERT INTO pd_driver_documents(telegram_id,side,image,updated_at) "
        "VALUES(?,?,?,?) ON CONFLICT(telegram_id,side) DO NOTHING",
        (applicant, side, image, datetime.now(timezone.utc).isoformat()),
    )
    if result.rowcount != 1:
        raise DocumentStorageError("Saved document cannot be replaced by pilot")
    return {"inserted": True, "side": side, "sha256": _sha(image)}


def dispatcher_replace(conn, *, applicant, side, image, expected_sha256,
                       actor_id, is_admin):
    """Authorized dispatcher replacement with SHA compare and append-only audit.

    The caller must take BEGIN IMMEDIATE and wrap any exception in a rollback.
    Invalidates the old review explicitly: the new file is PENDING.
    """
    _transaction(conn)
    _check_id(applicant)
    _check_id(actor_id)
    _check_side(side)
    _check_bytes(image)
    _check_lease(expected_sha256)
    if not callable(is_admin) or is_admin(actor_id) is not True:
        raise PermissionError("Dispatcher authorization required")
    _schema(conn, require_audit=True)
    status, stage = _app(conn, applicant)
    if status not in ("pending", "stage2") or stage not in (1, 2):
        raise DocumentStorageError("Cannot replace an approved or inactive pilot document")
    if stage == 1 and side not in review.FIRST:
        raise DocumentStorageError("Document is not part of current stage")
    row = conn.execute(
        "SELECT image FROM pd_driver_documents WHERE telegram_id=? AND side=?",
        (applicant, side),
    ).fetchone()
    if row is None:
        raise DocumentStorageError("No saved document; use upload flow")
    before = _sha(bytes(row[0]))
    if before != expected_sha256:
        raise DocumentStorageError("Document changed; reopen the current image")
    after = _sha(image)
    if before == after:
        return {"changed": False, "status": review.states(conn, applicant)[side]["status"]}
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE pd_driver_documents SET image=?,updated_at=? WHERE telegram_id=? AND side=?",
        (image, now, applicant, side),
    )
    conn.execute(
        "DELETE FROM pd_document_reviews WHERE telegram_id=? AND side=?",
        (applicant, side),
    )
    conn.execute(
        "INSERT INTO pd_document_replacements "
        "(telegram_id,side,actor_id,previous_sha256,replacement_sha256,replaced_at,action) "
        "VALUES(?,?,?,?,?,?,'dispatcher_replace')",
        (applicant, side, actor_id, before, after, now),
    )
    return {"changed": True, "status": "pending", "sha256": after}
