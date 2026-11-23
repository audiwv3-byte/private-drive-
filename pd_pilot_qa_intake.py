"""Isolated PRIVATE DRIVE pilot application intake.

Disabled by default. Requires a separate durable PostgreSQL database, Fernet
encryption key, and a high-entropy tester invitation. Never call from Mini App.
Real identity documents must not be used in staging without a privacy review.
"""
import hashlib
import hmac
import io
import os
import re
import secrets
import time
from collections import defaultdict, deque

from flask import Response, abort, jsonify, request

FILE_FIELDS = ("portrait", "license_front", "car_front", "car_rear")
MAX_FILE = 10 * 1024 * 1024
MAX_REQUEST = 4 * MAX_FILE + 1024 * 1024
RATE_LIMIT = 3


def configured():
    return (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.environ.get("PD_PILOT_QA_INTAKE_ENABLED") == "1"
            and os.environ.get("PD_PILOT_QA_DATABASE_URL", "").startswith(
                ("postgresql://", "postgres://"))
            and len(os.environ.get("PD_PILOT_QA_INVITE_SECRET", "")) >= 32
            and len(os.environ.get("PD_PILOT_QA_FERNET_KEY", "")) >= 40)


def image_as_private_webp(raw):
    """Decode, reject unsafe/unparseable formats and strip source metadata."""
    if not raw or len(raw) > MAX_FILE:
        raise ValueError("invalid_photo_size")
    from PIL import Image, ImageOps, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = 16_000_000
    try:
        with Image.open(io.BytesIO(raw)) as inspection:
            if inspection.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("invalid_photo_format")
            inspection.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if source.width < 1 or source.height < 1:
                raise ValueError("invalid_photo_dimensions")
            # Strip EXIF, GPS, thumbnails and container metadata by re-encoding.
            picture = ImageOps.exif_transpose(source).convert("RGB")
            picture.thumbnail((2400, 2400))
            buf = io.BytesIO()
            picture.save(buf, format="WEBP", quality=86, method=4)
            data = buf.getvalue()
            if not data or len(data) > MAX_FILE:
                raise ValueError("invalid_photo_size")
            return data
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("invalid_photo_format") from exc


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS pd_qa_pilot_applications (
            id TEXT PRIMARY KEY, full_name BYTEA NOT NULL,
            phone BYTEA NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','approved','rejected')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS pd_qa_pilot_documents (
            application_id TEXT NOT NULL REFERENCES pd_qa_pilot_applications(id)
                ON DELETE CASCADE,
            kind TEXT NOT NULL, encrypted_bytes BYTEA NOT NULL,
            PRIMARY KEY(application_id,kind)
        )""")


def register(app, authorized):
    """Mount fail-closed endpoints only on isolated staging app."""
    attempts = defaultdict(deque)

    def db():
        import psycopg
        return psycopg.connect(os.environ["PD_PILOT_QA_DATABASE_URL"])

    def cipher():
        from cryptography.fernet import Fernet
        return Fernet(os.environ["PD_PILOT_QA_FERNET_KEY"].encode("ascii"))

    @app.post("/pilot-registration")
    def qa_submit_pilot():
        if not configured():
            return jsonify(error="pilot_intake_disabled"), 503
        if (request.headers.get("Origin") not in
                (request.host_url.rstrip("/"), "https://" + request.host)):
            return jsonify(error="invalid_origin"), 403
        if (request.content_length is None or request.content_length > MAX_REQUEST
                or request.mimetype != "multipart/form-data"):
            return jsonify(error="invalid_upload"), 413
        ip = request.remote_addr or "unknown"
        now = time.monotonic()
        history = attempts[ip]
        while history and history[0] < now - 3600:
            history.popleft()
        if len(history) >= RATE_LIMIT:
            return jsonify(error="rate_limited"), 429
        history.append(now)
        supplied = request.form.get("qa_invitation", "")
        secret = os.environ["PD_PILOT_QA_INVITE_SECRET"]
        if not isinstance(supplied, str) or not hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(),
                hashlib.sha256(secret.encode()).digest()):
            return jsonify(error="invalid_invitation"), 403
        name, phone = (request.form.get("full_name", "").strip(),
                       request.form.get("phone", "").strip())
        if (not 2 <= len(name) <= 160 or not re.fullmatch(r"\+?[0-9 -]{8,32}", phone)):
            return jsonify(error="invalid_contact"), 400
        if set(request.files) != set(FILE_FIELDS):
            return jsonify(error="required_photos_missing"), 400
        try:
            images = {}
            for kind in FILE_FIELDS:
                upload = request.files[kind]
                # Never trust client-reported MIME or filename extensions.
                data = upload.stream.read(MAX_FILE + 1)
                images[kind] = image_as_private_webp(data)
            key = cipher()
            app_id = secrets.token_hex(16)
            with db() as conn:
                init_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("""INSERT INTO pd_qa_pilot_applications
                        (id,full_name,phone,status) VALUES (%s,%s,%s,'pending')""",
                        (app_id, key.encrypt(name.encode()),
                         key.encrypt(phone.encode())))
                    for kind, data in images.items():
                        cur.execute("""INSERT INTO pd_qa_pilot_documents
                            (application_id,kind,encrypted_bytes) VALUES (%s,%s,%s)""",
                            (app_id,kind,key.encrypt(data)))
            return jsonify(ok=True, application_id=app_id,
                           status="pending", label="На проверке", qa_only=True), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("QA pilot intake storage unavailable")
            return jsonify(error="storage_unavailable"), 503

    @app.get("/dispatch/pilot-applications")
    def qa_pilot_review_page():
        if not authorized():
            return jsonify(error="unauthorized"), 401
        # The review page never embeds PII into HTML; the protected API returns
        # decrypted values only to the currently authenticated dispatcher.
        page = """<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>PRIVATE DRIVE — анкеты пилотов QA</title>
<style>body{margin:0;padding:24px;background:#100f0d;color:#f2ede1;font:15px system-ui}
main{max-width:850px;margin:auto}h1,a{color:#e8c581}
article{border:1px solid #675234;padding:15px;margin:12px 0;border-radius:12px;background:#201b14}
small{color:#c8bba3}a{display:inline-block;margin:8px 14px 4px 0}
a:focus-visible{outline:3px solid #e8c581}#status{color:#e8c581}</style></head>
<body><main><h1>Анкеты пилотов — тестовая модерация</h1>
<p>Защищённая очередь. Статус новых анкет: «На проверке».</p>
<p id="status" role="status">Проверяем подключение…</p>
<div id="applications"></div>
<a href="/dispatch/map">Вернуться в диспетчерскую</a></main>
<script>
(async()=>{
 const target=document.getElementById("applications"),status=document.getElementById("status");
 try{
   const response=await fetch("/dispatch/qa-pilot-applications",{credentials:"same-origin",cache:"no-store"});
   const data=await response.json();
   if(!response.ok)throw Error(response.status===503?"Защищённое хранилище пока не настроено.":"Нет доступа к анкетам.");
   status.textContent="Анкет: "+data.applications.length;
   for(const app of data.applications){
     const card=document.createElement("article");
     for(const text of [app.full_name,app.phone,app.label,"Подана: "+app.created_at]){
       const p=document.createElement("p");p.textContent=text;card.append(p);
     }
     for(const [kind,label] of [["portrait","Фото пилота"],["license_front","Права"],["car_front","Автомобиль спереди"],["car_rear","Автомобиль сзади"]]){
       const link=document.createElement("a");
       link.href="/dispatch/qa-pilot-applications/"+encodeURIComponent(app.id)+"/documents/"+kind;
       link.textContent=label;link.rel="noreferrer";card.append(link);
     }
     target.append(card);
   }
   if(!data.applications.length)target.textContent="Анкет на проверке пока нет.";
 }catch(error){status.textContent=error.message}
})();
</script></body></html>"""
        return Response(page, mimetype="text/html", headers={
            "Cache-Control":"private, no-store",
            "X-Content-Type-Options":"nosniff",
            "Referrer-Policy":"no-referrer",
            "X-Frame-Options":"DENY",
            "Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        })

    @app.get("/dispatch/qa-pilot-applications")
    def qa_pilots_for_dispatcher():
        if not authorized():
            return jsonify(error="unauthorized"), 401
        if not configured():
            return jsonify(error="pilot_intake_disabled"), 503
        try:
            key = cipher()
            with db() as conn:
                init_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("""SELECT id,full_name,phone,status,created_at
                        FROM pd_qa_pilot_applications ORDER BY created_at DESC LIMIT 50""")
                    data = [
                        {"id":row[0], "full_name":key.decrypt(bytes(row[1])).decode(),
                         "phone":key.decrypt(bytes(row[2])).decode(),
                         "status":row[3], "label":"На проверке" if row[3]=="pending" else row[3],
                         "created_at":row[4].isoformat()}
                        for row in cur.fetchall()
                    ]
            return jsonify(applications=data), 200, {"Cache-Control":"private, no-store"}
        except Exception:
            app.logger.exception("QA pilot application list unavailable")
            return jsonify(error="storage_unavailable"), 503

    @app.get("/dispatch/qa-pilot-applications/<app_id>/documents/<kind>")
    def qa_pilot_private_image(app_id, kind):
        if not authorized():
            return jsonify(error="unauthorized"), 401
        if not configured():
            return jsonify(error="pilot_intake_disabled"), 503
        if not re.fullmatch(r"[a-f0-9]{32}", app_id) or kind not in FILE_FIELDS:
            abort(404)
        try:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT encrypted_bytes FROM pd_qa_pilot_documents
                        WHERE application_id=%s AND kind=%s""", (app_id,kind))
                    result = cur.fetchone()
            if not result:
                abort(404)
            content = cipher().decrypt(bytes(result[0]))
            return Response(content, mimetype="image/webp", headers={
                "Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff",
                "Content-Disposition":'attachment; filename="qa-photo.webp"',
                "Content-Security-Policy":"default-src 'none'; sandbox",
            })
        except Exception as exc:
            from werkzeug.exceptions import HTTPException
            if isinstance(exc, HTTPException):
                raise
            app.logger.exception("QA pilot document retrieval unavailable")
            return jsonify(error="storage_unavailable"), 503
