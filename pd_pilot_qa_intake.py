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
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from collections import defaultdict, deque

from flask import Response, abort, jsonify, render_template_string, request

FILE_FIELDS = ("portrait", "license_front", "car_front", "car_rear")
REQUIRED_PHOTOS = ("license_front", "car_front")
MAX_FILE = 10 * 1024 * 1024
MAX_REQUEST = 2 * MAX_FILE + 1024 * 1024
RATE_LIMIT = 3
TERMS_VERSION = "pilot-shift-v1"


def configured():
    return (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.environ.get("PD_PILOT_QA_INTAKE_ENABLED") == "1"
            and os.environ.get("PD_PILOT_QA_DATABASE_URL", "").startswith(
                ("postgresql://", "postgres://"))
            and len(os.environ.get("PD_PILOT_QA_INVITE_SECRET", "")) >= 32
            and len(os.environ.get("PD_PILOT_QA_FERNET_KEY", "")) >= 40)


def register_production_form(app, directory):
    """Keep production intake disabled until owner-only configuration exists."""
    key_path = directory / "pilot-intake.key"
    invite_path = directory / "pilot-intake.invite"
    if not key_path.is_file() or not invite_path.is_file():
        return None
    from cryptography.fernet import Fernet
    key = Fernet(key_path.read_bytes().strip())
    invitation = invite_path.read_text().strip()
    if len(invitation) < 32:
        raise ValueError("Pilot invitation must have at least 32 characters")

    @contextmanager
    def db():
        with closing(sqlite3.connect(directory / "pilot-intake.sqlite3", timeout=10)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn

    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pd_qa_pilot_applications (
                id TEXT PRIMARY KEY, full_name BLOB NOT NULL, phone BLOB NOT NULL,
                email BLOB NOT NULL, plate BLOB NOT NULL, status TEXT NOT NULL,
                terms_version TEXT NOT NULL, accepted_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                pilot_number INTEGER UNIQUE
            );
            CREATE TABLE IF NOT EXISTS pd_qa_pilot_documents (
                application_id TEXT NOT NULL REFERENCES pd_qa_pilot_applications(id),
                kind TEXT NOT NULL, encrypted_bytes BLOB NOT NULL,
                PRIMARY KEY(application_id,kind)
            );
        """)

    @app.get("/pilot-registration")
    def pilot_registration():
        template = Path(__file__).with_name("pd_pilot_registration.html").read_text(encoding="utf-8")
        return Response(render_template_string(template, enabled=True, production=True),
                        mimetype="text/html", headers={
                            "Cache-Control": "no-store",
                            "Content-Security-Policy": "default-src 'none'; img-src 'self'; "
                            "style-src 'self' 'unsafe-inline'; script-src 'unsafe-inline'; "
                            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                            "Referrer-Policy": "no-referrer",
                            "X-Content-Type-Options": "nosniff",
                        })

    return db, key, invitation


def image_as_private_webp(raw):
    """Decode, reject unsafe/unparseable formats and strip source metadata."""
    if not raw or len(raw) > MAX_FILE:
        raise ValueError("invalid_photo_size")
    # Reject unknown uploads before invoking the image decoder.
    is_jpeg = raw.startswith(bytes.fromhex("ffd8ff"))
    is_png = raw.startswith(bytes.fromhex("89504e470d0a1a0a"))
    is_webp = raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    if not (is_jpeg or is_png or is_webp):
        raise ValueError("invalid_photo_format")
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
        cur.execute("ALTER TABLE pd_qa_pilot_applications ADD COLUMN IF NOT EXISTS email BYTEA")
        cur.execute("""ALTER TABLE pd_qa_pilot_applications
            ADD COLUMN IF NOT EXISTS plate BYTEA,
            ADD COLUMN IF NOT EXISTS terms_version TEXT,
            ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS pilot_number BIGINT UNIQUE""")
        cur.execute("CREATE SEQUENCE IF NOT EXISTS pd_qa_pilot_numbers")
        cur.execute("""CREATE TABLE IF NOT EXISTS pd_qa_pilot_documents (
            application_id TEXT NOT NULL REFERENCES pd_qa_pilot_applications(id)
                ON DELETE CASCADE,
            kind TEXT NOT NULL, encrypted_bytes BYTEA NOT NULL,
            PRIMARY KEY(application_id,kind)
        )""")


def register(app, authorized, csrf, valid_csrf, *, production=None):
    """Mount fail-closed endpoints only on isolated staging app."""
    attempts = defaultdict(deque)

    def ready():
        return production is not None or configured()

    def db():
        if production:
            return production[0]()
        import psycopg
        return psycopg.connect(os.environ["PD_PILOT_QA_DATABASE_URL"])

    def cipher():
        if production:
            return production[1]
        from cryptography.fernet import Fernet
        return Fernet(os.environ["PD_PILOT_QA_FERNET_KEY"].encode("ascii"))

    def cursor(conn):
        return closing(conn.cursor()) if production else conn.cursor()

    def execute(cur, sql, args=()):
        if production:
            sql = sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP")
        return cur.execute(sql, args)

    @app.post("/pilot-registration")
    def qa_submit_pilot():
        if not ready():
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
        secret = production[2] if production else os.environ["PD_PILOT_QA_INVITE_SECRET"]
        if not isinstance(supplied, str) or not hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(),
                hashlib.sha256(secret.encode()).digest()):
            return jsonify(error="invalid_invitation"), 403
        first = request.form.get("first_name", "").strip()
        last = request.form.get("last_name", "").strip()
        name = f"{first} {last}"
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        if (not 1 <= len(first) <= 80 or not 1 <= len(last) <= 80
                or not re.fullmatch(r"\+?[0-9 -]{8,32}", phone)
                or not 8 <= sum(ch.isdigit() for ch in phone) <= 15
                or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
            return jsonify(error="invalid_contact"), 400
        plate = request.form.get("plate", "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{1,14}", plate):
            return jsonify(error="invalid_plate"), 400
        if request.form.get("terms_version") != TERMS_VERSION:
            return jsonify(error="terms_required"), 400
        if set(request.files) != set(REQUIRED_PHOTOS) or any(
                len(request.files.getlist(kind)) != 1 for kind in REQUIRED_PHOTOS):
            return jsonify(error="required_photos_missing"), 400
        try:
            images = {}
            for kind in REQUIRED_PHOTOS:
                upload = request.files[kind]
                # Never trust client-reported MIME or filename extensions.
                data = upload.stream.read(MAX_FILE + 1)
                images[kind] = image_as_private_webp(data)
            key = cipher()
            app_id = secrets.token_hex(16)
            with db() as conn:
                if not production:
                    init_schema(conn)
                with cursor(conn) as cur:
                    execute(cur, """INSERT INTO pd_qa_pilot_applications
                        (id,full_name,phone,email,status,plate,terms_version,accepted_at)
                        VALUES (%s,%s,%s,%s,'pending',%s,%s,NOW())""",
                        (app_id, key.encrypt(name.encode()),
                         key.encrypt(phone.encode()), key.encrypt(email.encode()),
                         key.encrypt(plate.encode()), TERMS_VERSION))
                    for kind, data in images.items():
                        execute(cur, """INSERT INTO pd_qa_pilot_documents
                            (application_id,kind,encrypted_bytes) VALUES (%s,%s,%s)""",
                            (app_id,kind,key.encrypt(data)))
            return jsonify(ok=True, application_id=app_id,
                           status="pending", label="На проверке", qa_only=production is None), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("QA pilot intake storage unavailable")
            return jsonify(error="storage_unavailable"), 503

    @app.post("/dispatch/qa-pilot-applications/<app_id>/approve")
    def approve_application(app_id):
        if not authorized() or not valid_csrf():
            abort(403)
        if not ready():
            abort(503)
        with db() as conn, cursor(conn) as cur:
            if production:
                execute(cur, "BEGIN IMMEDIATE")
            next_number = "(SELECT COALESCE(MAX(pilot_number), 0) + 1 FROM pd_qa_pilot_applications)" if production else "nextval('pd_qa_pilot_numbers')"
            execute(cur, f"""UPDATE pd_qa_pilot_applications
                SET status='approved', pilot_number={next_number}
                WHERE id=%s AND status='pending' AND terms_version=%s
                AND plate IS NOT NULL RETURNING pilot_number""", (app_id, TERMS_VERSION))
            result = cur.fetchone()
            if result is None:
                execute(cur, """SELECT pilot_number FROM pd_qa_pilot_applications
                    WHERE id=%s AND status='approved'""", (app_id,))
                result = cur.fetchone()
            if result is None:
                abort(409)
        return jsonify(pilot_number=result[0])

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
     for(const text of [app.full_name,app.plate,app.pilot_number && "Пилот №"+app.pilot_number,app.label,"Подана: "+app.created_at]){
       if(!text)continue;
       const p=document.createElement("p");p.textContent=text;card.append(p);
     }
     for(const [kind,label] of [["portrait","Фото пилота"],["license_front","Права"],["car_front","Фото автомобиля"],["car_rear","Автомобиль сзади"]]){
       if(!app.documents.includes(kind))continue;
       const link=document.createElement("a");
       link.href="/dispatch/qa-pilot-applications/"+encodeURIComponent(app.id)+"/documents/"+kind;
       link.textContent=label;link.rel="noreferrer";card.append(link);
     }
     for(const [value,scheme] of [[app.phone,"tel:"],[app.email,"mailto:"]]){
       if(!value)continue;
       const contact=document.createElement("a");
       contact.href=scheme+value;contact.textContent=value;card.append(contact);
     }
     if(app.status==="pending" && app.terms_version){
       const approve=document.createElement("button");
       approve.textContent="Одобрить анкету";
       approve.onclick=async()=>{
         approve.disabled=true;
         try{
           const reply=await fetch("/dispatch/qa-pilot-applications/"+app.id+"/approve",{
             method:"POST",body:new URLSearchParams({csrf:data.csrf})});
           if(!reply.ok)throw Error();
           location.reload();
         }catch{approve.disabled=false;status.textContent="Не удалось подтвердить одобрение.";}
       };
       card.append(approve);
     }
     target.append(card);
   }
   if(!data.applications.length)target.textContent="Анкет на проверке пока нет.";
 }catch(error){status.textContent=error.message}
})();
</script></body></html>"""
        if production:
            page = page.replace("анкеты пилотов QA", "анкеты пилотов").replace(" — тестовая модерация", "")
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
        if not ready():
            return jsonify(error="pilot_intake_disabled"), 503
        try:
            key = cipher()
            with db() as conn:
                if not production:
                    init_schema(conn)
                with cursor(conn) as cur:
                    document_list = ("(SELECT group_concat(kind) FROM pd_qa_pilot_documents WHERE application_id=a.id)"
                                     if production else "ARRAY(SELECT kind FROM pd_qa_pilot_documents WHERE application_id=a.id)")
                    execute(cur, f"""SELECT id,full_name,phone,status,created_at,email,
                        {document_list}, plate,terms_version,pilot_number
                        FROM pd_qa_pilot_applications a ORDER BY created_at DESC LIMIT 50""")
                    data = [
                        {"id":row[0], "full_name":key.decrypt(bytes(row[1])).decode(),
                         "phone":key.decrypt(bytes(row[2])).decode(),
                         "status":row[3], "label":"На проверке" if row[3]=="pending" else {"approved":"Одобрена","rejected":"Отклонена"}.get(row[3],row[3]),
                         "created_at":row[4] if production else row[4].isoformat(),
                         "email":key.decrypt(bytes(row[5])).decode() if row[5] else "",
                         "documents":(row[6] or "").split(",") if production else row[6], "plate":key.decrypt(bytes(row[7])).decode() if row[7] else "",
                         "terms_version":row[8], "pilot_number":row[9]}
                        for row in cur.fetchall()
                    ]
            return jsonify(applications=data, csrf=csrf()), 200, {"Cache-Control":"private, no-store"}
        except Exception:
            app.logger.exception("QA pilot application list unavailable")
            return jsonify(error="storage_unavailable"), 503

    @app.get("/dispatch/qa-pilot-applications/<app_id>/documents/<kind>")
    def qa_pilot_private_image(app_id, kind):
        if not authorized():
            return jsonify(error="unauthorized"), 401
        if not ready():
            return jsonify(error="pilot_intake_disabled"), 503
        if not re.fullmatch(r"[a-f0-9]{32}", app_id) or kind not in FILE_FIELDS:
            abort(404)
        try:
            with db() as conn:
                with cursor(conn) as cur:
                    execute(cur, """SELECT encrypted_bytes FROM pd_qa_pilot_documents
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
