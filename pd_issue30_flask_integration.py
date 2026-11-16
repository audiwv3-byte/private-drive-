"""Issue #30 offline Flask integration harness — NOT installed in PythonAnywhere.

Uses the same intended path/method semantics, but is not a drop-in
replacement for the live onboarding handler. Must be integrated by replacing
the existing INSERT ... ON CONFLICT DO UPDATE inside deployed transaction,
not by adding a before_request check or a competing route.

All file validation must be provided by the deployed image-normalization
pipeline. No automatic register() call. Test-only run with synthetic image bytes.
"""
from flask import jsonify, request
import pd_issue30_document_storage_guard as store
import pd_document_review as reviews

MAX_IMAGE = 10 * 1024 * 1024


def assert_no_legacy_upsert(source_text):
    """Deployment blocker: fail if old direct image UPSERT remains."""
    import re
    if re.search(
        r"ON\s+CONFLICT\s*\(\s*telegram_id\s*,\s*side\s*\)"
        r"\s+DO\s+UPDATE\s+SET\s+image\s*=",
        source_text, flags=re.I,
    ):
        raise RuntimeError("Legacy document UPSERT must be removed from deployed upload path")
    return True


def _photo(validate_photo):
    f = request.files.get("image")
    if f is None:
        raise store.DocumentStorageError("Missing document image")
    # This limit is preliminary; deployed validator must decode and normalize
    # actual JPEG/PNG/WEBP and reject malicious or oversized formats.
    data = f.read(MAX_IMAGE + 1)
    if not data or len(data) > MAX_IMAGE:
        raise store.DocumentStorageError("Invalid document image size")
    image = validate_photo(data)
    if type(image) is not bytes or not image or len(image) > MAX_IMAGE:
        raise store.DocumentStorageError("Image validator did not return bounded bytes")
    return image


def register_offline_routes(app, core, auth, validate_photo, *, allow_synthetic=False):
    """Never called on live Flask. Explicit opt-in test fixture only.

    core.db(core.USERS_DB) must yield caller-owned SQLite connection with
    transactions; auth() returns (server-trusted Telegram ID, metadata).
    """
    if allow_synthetic is not True or app.config.get("TESTING") is not True:
        raise RuntimeError("Production registration deliberately disabled")
    if not callable(validate_photo):
        raise TypeError("Image validator required")

    @app.errorhandler(store.DocumentStorageError)
    def error_storage(err):
        return jsonify(error=str(err)), 409

    @app.errorhandler(PermissionError)
    def error_forbidden(err):
        return jsonify(error="Access denied"), 403

    @app.post("/api/driver/application/documents/<side>")
    def offline_pilot_upload(side):
        uid, _ = auth()
        image = _photo(validate_photo)
        # Existing live application row must be written/validated in SAME
        # transaction BEFORE this operation. Synthetic harness has such row.
        with core.db(core.USERS_DB) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = store.pilot_insert_missing(
                    conn, applicant=uid, side=side, image=image
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return jsonify(result), 201

    @app.post("/api/admin/driver-applications/<int:applicant>/documents/<side>/replace")
    def offline_dispatcher_replace(applicant, side):
        actor, _ = auth()
        # Reject before any file processing for unauthorized callers.
        if type(actor) is not int or core.is_admin(actor) is not True:
            raise PermissionError("Not a dispatcher")
        lease = request.form.get("expected_sha256")
        if not isinstance(lease, str):
            raise store.DocumentStorageError("Expected document revision is required")
        image = _photo(validate_photo)
        with core.db(core.USERS_DB) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = store.dispatcher_replace(
                    conn, applicant=applicant, side=side, image=image,
                    expected_sha256=lease, actor_id=actor, is_admin=core.is_admin
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return jsonify(result)
