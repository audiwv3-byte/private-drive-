"""One-at-a-time, access-controlled native photo review for the existing web dispatcher."""
import base64
import hashlib
import hmac
import os
import re
import secrets

from flask import Response, render_template_string, request

from pd_native_pilot_assignment import _connect, _database_target

ROUTE = "/dispatch/native-photo-review"
_MAX_FORM = 2048
_MAX_JPEG = 2 * 1024 * 1024
_CLAIM = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_PROOF = re.compile(r"[a-f0-9]{64}\Z")

_PAGE = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>PRIVATE DRIVE · Фотопроверка пилотов</title>
<main><h1>Фотопроверка пилотов</h1>
<p><a href="/dispatch">Вернуться в диспетчерский кабинет</a></p>
<p role="status">{{ notice }}</p>
{% if csrf %}
{% if image %}
<img src="{{ image }}" alt="Фото пилота для текущей проверки" width="480">
{% endif %}
<form method="post" action="{{ route }}">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Текущий пароль диспетчера
    <input type="password" name="password" required maxlength="512" autocomplete="current-password">
  </label>
  {% if image %}
  <input type="hidden" name="action" value="decide">
  <input type="hidden" name="claim" value="{{ claim }}">
  <button name="decision" value="approved">Одобрить</button>
  <button name="decision" value="rejected">Отклонить</button>
  {% else %}
  <input type="hidden" name="action" value="open">
  <button>Открыть одну заявку</button>
  {% endif %}
</form>
{% endif %}
</main></html>"""


def photo_review_database():
    if (os.getenv("PD_DISPATCH_STAGING_ONLY") != "1"
            or os.getenv("PD_WEB_NATIVE_PHOTO_REVIEW") != "1"
            or os.getenv("PD_PAYMENT_MODE") != "disabled"):
        return None
    reader = os.getenv("PD_DISPATCH_ORDERS_DATABASE_URL", "")
    reviewer = os.getenv("PD_WEB_NATIVE_PHOTO_REVIEW_DATABASE_URL", "")
    if not all(value.startswith(("postgresql://", "postgres://")) for value in (reader, reviewer)):
        return None
    target = _database_target(reader)
    if target is None or target != _database_target(reviewer):
        return None
    return reviewer


def web_review_credential_proof(secret, admin_id, credential_version):
    """A binding proof unknown to the browser, separate from cookie MACs."""
    message = f"private-drive-native-web-photo-review:v1:{admin_id}:{credential_version}"
    return hmac.new(secret.encode("utf-8"), message.encode("ascii"), hashlib.sha256).hexdigest()


def _bound_claim(csrf_token, claim):
    # The new login CSRF nonce makes an otherwise valid claim unusable from a
    # different browser session, even for the same dispatcher credential.
    return hashlib.sha256((csrf_token + ":" + claim).encode("ascii")).hexdigest()


def register_web_native_photo_review(app, reviewer_context, verify_password,
                                     allow_attempt, csrf, valid_csrf):
    def page(status, notice, *, form=False, photo=None, claim=None):
        # No third-party assets, scripts, external image hosts, cache, or
        # permanent photo URLs. Inline photo is never included on GET.
        image = None
        if photo is not None:
            image = "data:image/jpeg;base64," + base64.b64encode(photo).decode("ascii")
        html = render_template_string(_PAGE, notice=notice, csrf=csrf() if form else None,
                                      route=ROUTE, image=image, claim=claim)
        return Response(html, status=status, content_type="text/html; charset=utf-8", headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Referrer-Policy": "no-referrer",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'none'; img-src data:; "
                                       "form-action 'self'; frame-ancestors 'none'; "
                                       "base-uri 'none'; object-src 'none'",
        })

    @app.route(ROUTE, methods=("GET", "POST"))
    def pd_web_native_photo_review():
        # Do not accept any browser-supplied admin/native actor or credential
        # version. This identity comes only from the existing signed session.
        actor = reviewer_context()
        if actor is None:
            return page(401, "Войди в диспетчерский кабинет.")
        admin_id, proof = actor
        if (type(admin_id) is not int or not 0 < admin_id < 10**18
                or not isinstance(proof, str) or not _PROOF.fullmatch(proof)):
            return page(403, "Доступ к фотопроверке недоступен.")
        database = photo_review_database()
        if database is None:
            return page(503, "Фотопроверка пока закрыта.")
        if request.query_string:
            return page(400, "Недопустимый запрос.")
        if request.method == "GET":
            return page(200, "Для открытия одной заявки подтверди текущий пароль.", form=True)

        if (request.mimetype != "application/x-www-form-urlencoded"
                or request.content_length is None
                or not 0 < request.content_length <= _MAX_FORM):
            return page(400, "Недопустимый запрос.")
        if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
            return page(403, "Недопустимый запрос.")
        if not valid_csrf():
            return page(403, "Защитный токен не совпал. Открой раздел заново.")
        action = request.form.get("action")
        fields = {"action", "csrf", "password"}
        if action == "decide":
            fields |= {"claim", "decision"}
        if (action not in ("open", "decide") or set(request.form) != fields
                or any(len(request.form.getlist(key)) != 1 for key in fields)):
            return page(400, "Недопустимый запрос.")
        if action == "decide":
            claim = request.form["claim"]
            decision = request.form["decision"]
            if not _CLAIM.fullmatch(claim) or decision not in ("approved", "rejected"):
                return page(400, "Недопустимый запрос.")
        password = request.form["password"]
        if not 1 <= len(password) <= 512:
            return page(400, "Недопустимый запрос.")
        if not allow_attempt():
            return page(429, "Слишком много проверок пароля. Повтори позже.")
        if not verify_password(password):
            return page(403, "Текущий пароль не подтверждён.")

        # Both actions require a fresh password and request CSRF. A captured
        # claim alone (even with copied old auth cookie) is not enough.
        try:
            if action == "open":
                claim = secrets.token_urlsafe(32)
                with _connect(database) as db:
                    result = db.execute(
                        "SELECT public.pd_open_web_native_photo_review(%s,%s,%s)",
                        (admin_id, proof, _bound_claim(csrf(), claim)),
                    ).fetchone()
                if not result or result[0] is None:
                    return page(409, "Нет доступной заявки или уже открыта одна проверка.", form=True)
                photo = bytes(result[0])
                if not 4 <= len(photo) <= _MAX_JPEG or not photo.startswith(b"\xff\xd8") or not photo.endswith(b"\xff\xd9"):
                    return page(503, "Фото недоступно.")
                return page(200, "Сверь фото и подтверди решение. Открытая заявка действует до трёх минут.",
                            form=True, photo=photo, claim=claim)

            with _connect(database) as db:
                result = db.execute(
                    "SELECT public.pd_decide_web_native_photo_review(%s,%s,%s,%s)",
                    (admin_id, proof, _bound_claim(csrf(), claim), decision),
                ).fetchone()
            if not result or result[0] is not True:
                return page(409, "Заявка больше недоступна.", form=True)
            return page(200, "Решение сохранено.", form=True)
        except Exception:
            # No request, user ID, DSN, photo, credential or detailed DB error
            # in app logs. The failure must never fall back to a broad reader.
            app.logger.warning("Native photo review unavailable")
            return page(503, "Фотопроверка временно недоступна.")
