"""Issue #30 opt-in server route integration — DOES NOT AUTO-REGISTER.

Use only in a separately approved, atomic production release, after review
and replacement audit tables are migrated. The existing live auth() and core
are injected by the WSGI application, never taken from request headers/JSON.
"""
import pd_document_review as reviews
import pd_issue30_document_storage_guard as storage
from pd_issue30_connection import managed_core_db


def register(app, core, auth, normalized_photos):
    """Opt-in registration, no WSGI import side effects.

    normalized_photos must be the deployed pd_onboarding.read_photos(sides)
    function, so its PIL validation/max size/normalization are retained.
    """
    if not callable(auth) or not callable(normalized_photos):
        raise TypeError("Server auth and deployed photo normalizer required")

    # Existing role-protected metadata GET + document decision POST routes.
    reviews.register(app, core, auth)

    from flask import jsonify, request

    @app.post("/api/admin/driver-applications/<int:applicant>/documents/<side>/replace")
    def issue30_dispatcher_replace_document(applicant, side):
        actor, _ = auth()
        if type(actor) is not int or actor <= 0 or core.is_admin(actor) is not True:
            raise PermissionError("Доступ только диспетчеру")
        if side not in reviews.SIDES:
            raise storage.DocumentStorageError("Неизвестная сторона документа")
        if request.mimetype != "multipart/form-data":
            raise storage.DocumentStorageError("Ожидается загрузка фотографии")
        expected_sha256 = request.form.get("expected_sha256", "")
        if side not in request.files:
            raise storage.DocumentStorageError("Добавь фотографию документа")
        # Production normalizer is invoked only AFTER server-side role check.
        validated = normalized_photos((side,))
        image = validated.get(side)
        if not image:
            raise storage.DocumentStorageError("Не удалось проверить фотографию")

        with managed_core_db(core) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = storage.dispatcher_replace(
                    conn, applicant=applicant, side=side,
                    image=image, expected_sha256=expected_sha256,
                    actor_id=actor, is_admin=core.is_admin
                )
                # SQLite connection manager may also commit on normal exit;
                # explicit commit keeps behavior clear and prevents partial action.
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return jsonify(result)
