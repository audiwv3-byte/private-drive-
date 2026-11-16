"""Issue #30: isolated server-side document review, NOT enabled in production.

Integration point (after the live two-stage onboarding has been reconciled):
    register(app, core, auth)
and insert require_approved_documents(...) inside the existing ADMIN final
approval transaction. Never replace live pd_onboarding.py with GitHub main.

This module does not upload or overwrite images, grant pilot role, or modify
driver application status. It only records dispatcher reviews and audit history.
"""
import hashlib
import sqlite3
from datetime import datetime, timezone

SIDES = (
    "license_front", "license_back", "registration_front", "registration_back",
    "ltsa", "activity", "insurance", "portrait",
    "car_front", "car_rear", "car_interior",
)
FIRST = ("license_front", "license_back", "car_front", "car_rear", "car_interior")
SECOND = ("registration_front", "ltsa", "activity", "insurance", "portrait")
VALID_ACTIONS = ("approved", "rejected")
MAX_REASON = 500


class ReviewError(ValueError):
    """Safe error to display to a dispatcher; no sensitive document content."""


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _hash(image):
    return hashlib.sha256(bytes(image)).hexdigest()


def _require_side(side):
    if side not in SIDES:
        raise ReviewError("Неизвестный тип документа")


def ensure_tables(conn):
    """Add only new tables; do not update legacy documents or applications.

    Existing uploaded files are effectively *pending*: no review row means
    approval is NOT granted.
    """
    conn.execute("""CREATE TABLE IF NOT EXISTS pd_document_reviews (
      telegram_id INTEGER NOT NULL,
      side TEXT NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('approved','rejected')),
      content_sha256 TEXT NOT NULL,
      reviewer_id INTEGER NOT NULL,
      reviewed_at TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (telegram_id,side))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pd_document_review_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      telegram_id INTEGER NOT NULL,
      side TEXT NOT NULL,
      decision TEXT NOT NULL,
      content_sha256 TEXT NOT NULL,
      reviewer_id INTEGER NOT NULL,
      reviewed_at TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT '')""")


def _document(conn, applicant, side):
    row = conn.execute(
        "SELECT image FROM pd_driver_documents WHERE telegram_id=? AND side=?",
        (applicant, side),
    ).fetchone()
    return bytes(row[0]) if row else None


def states(conn, applicant):
    """Returns metadata only, not photos or private application fields.

    Reviews for a previous photo SHA become pending on replacement. Old files
    without a review row are also pending.
    """
    result = {}
    for side in SIDES:
        blob = _document(conn, applicant, side)
        if blob is None:
            result[side] = {"status": "missing"}
            continue
        sha = _hash(blob)
        review = conn.execute(
            "SELECT status,content_sha256,reason,reviewed_at "
            "FROM pd_document_reviews WHERE telegram_id=? AND side=?",
            (applicant, side),
        ).fetchone()
        if review and review[1] == sha:
            result[side] = {
                "status": review[0],
                "reason": review[2] if review[0] == "rejected" else "",
                "reviewed_at": review[3],
                "sha256": sha,
            }
        else:
            result[side] = {"status": "pending", "sha256": sha}
    return result


def _ensure_applicant(conn, applicant):
    row = conn.execute(
        "SELECT telegram_id FROM pd_driver_applications WHERE telegram_id=?",
        (applicant,),
    ).fetchone()
    if row is None:
        raise ReviewError("Заявка пилота не найдена")


def decide(conn, *, applicant, side, action, reviewer_id, expected_sha256,
           reason="", reviewed_at=None):
    """Audited, idempotent decision for exact bytes a dispatcher inspected.

    Caller MUST check admin role before invoking. Lock with BEGIN IMMEDIATE to
    compare the stored bytes and expected SHA in one SQLite write transaction.
    """
    _require_side(side)
    if action not in VALID_ACTIONS:
        raise ReviewError("Допускается только одобрение или отклонение")
    if not isinstance(applicant, int) or isinstance(applicant, bool) or applicant < 1:
        raise ReviewError("Неверный идентификатор пилота")
    if not isinstance(reviewer_id, int) or isinstance(reviewer_id, bool) or reviewer_id < 1:
        raise ReviewError("Некорректный диспетчер")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ReviewError("Обнови документ перед проверкой")
    if not isinstance(reason, str) or len(reason.strip()) > MAX_REASON:
        raise ReviewError("Причина слишком длинная")
    reason = " ".join(reason.split())
    if action == "rejected" and len(reason) < 3:
        raise ReviewError("Укажи причину отклонения")
    if action == "approved":
        reason = ""
    now = reviewed_at or _utc()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_tables(conn)
        _ensure_applicant(conn, applicant)
        blob = _document(conn, applicant, side)
        if blob is None:
            raise ReviewError("Документ ещё не загружен")
        actual = _hash(blob)
        if actual != expected_sha256.lower():
            raise ReviewError("Документ обновлён. Открой его заново")
        existing = conn.execute(
            "SELECT status,content_sha256,reason FROM pd_document_reviews "
            "WHERE telegram_id=? AND side=?", (applicant, side),
        ).fetchone()
        if existing and existing[0] == action and existing[1] == actual and existing[2] == reason:
            conn.commit()
            return {"ok": True, "changed": False, "status": action}
        conn.execute(
            """INSERT INTO pd_document_reviews
               (telegram_id,side,status,content_sha256,reviewer_id,reviewed_at,reason)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(telegram_id,side) DO UPDATE SET
                 status=excluded.status,content_sha256=excluded.content_sha256,
                 reviewer_id=excluded.reviewer_id,reviewed_at=excluded.reviewed_at,
                 reason=excluded.reason""",
            (applicant, side, action, actual, reviewer_id, now, reason),
        )
        conn.execute(
            """INSERT INTO pd_document_review_events
               (telegram_id,side,decision,content_sha256,reviewer_id,reviewed_at,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (applicant, side, action, actual, reviewer_id, now, reason),
        )
        conn.commit()
        return {"ok": True, "changed": True, "status": action}
    except Exception:
        conn.rollback()
        raise


def require_approved_documents(conn, applicant, stage):
    """Must be called during final-approval transaction, server-side.

    No partial approval: both stages' required documents need current SHA
    matching an explicit admin approval. First-stage advance only checks FIRST.
    """
    if stage not in (1, 2):
        raise ReviewError("Неизвестный этап регистрации")
    ensure_tables(conn)
    current = states(conn, applicant)
    needed = FIRST if stage == 1 else FIRST + SECOND
    blocked = [side for side in needed if current[side]["status"] != "approved"]
    if blocked:
        raise ReviewError("Не одобрены обязательные документы: " + ", ".join(blocked))
    return True


def register(app, core, auth):
    """Opt-in Flask endpoints. Nothing registered until caller enables module.

    No data mutations on GET; server-side admin authorization on both routes.
    Existing /api/admin/driver-applications/:id/decision remains separate and
    MUST be patched to call require_approved_documents before production use.
    """
    from flask import jsonify, request

    def require_admin():
        uid, _ = auth()
        if not core.is_admin(uid):
            raise PermissionError("Нет доступа")
        return uid

    @app.get("/api/admin/driver-applications/<int:applicant>/document-reviews")
    def pd_document_review_list(applicant):
        require_admin()
        with core.db(core.USERS_DB) as conn:
            # Do not create DB tables in GET; migration must run first.
            return jsonify(documents=states(conn, applicant))

    @app.post("/api/admin/driver-applications/<int:applicant>/document-reviews/<side>")
    def pd_document_review_decide(applicant, side):
        reviewer_id = require_admin()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ReviewError("Неверные данные решения")
        with core.db(core.USERS_DB) as conn:
            result = decide(
                conn, applicant=applicant, side=side, reviewer_id=reviewer_id,
                action=payload.get("status"),
                expected_sha256=payload.get("sha256"),
                reason=payload.get("reason", ""),
            )
        return jsonify(result)
