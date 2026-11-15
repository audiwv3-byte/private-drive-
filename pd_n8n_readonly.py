"""Read-only, narrowly scoped n8n orders view. Disabled unless configured."""
import hmac
import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from flask import jsonify, request

def register(app, core):
    @app.get("/api/integrations/n8n/orders")
    def n8n_orders_readonly():
        supplied = request.headers.get("Authorization", "")
        if not supplied.startswith("Bearer "):
            return jsonify(error="Unauthorized"), 401

        # Prefer a SHA-256 verifier, so the bearer token need not be stored on
        # the web server. Store only this verifier in a private application file.
        verifier_path = Path(__file__).with_name(".pd_n8n_readonly.sha256")
        try:
            verifier = verifier_path.read_text(encoding="ascii").strip()
        except OSError:
            verifier = ""
        if len(verifier) == 64 and all(c in "0123456789abcdef" for c in verifier):
            digest = hashlib.sha256(supplied[7:].encode("utf-8")).hexdigest()
            authorized = hmac.compare_digest(digest, verifier)
        else:
            # Backward-compatible path for local unit tests; never enable by
            # default on the production server.
            expected = os.environ.get("PD_N8N_READONLY_TOKEN", "")
            authorized = len(expected) >= 32 and hmac.compare_digest(
                supplied[7:].encode(), expected.encode()
            )
        if not authorized:
            return jsonify(error="Unauthorized"), 401

        try:
            limit = int(request.args.get("limit", "20"))
        except ValueError:
            return jsonify(error="Invalid limit"), 400
        if not 1 <= limit <= 50:
            return jsonify(error="Invalid limit"), 400

        status = request.args.get("status")
        allowed = ("Новая", "Подтверждена", "В пути", "Выполнена", "Отменена")
        if status is not None and status not in allowed:
            return jsonify(error="Invalid status"), 400

        # SQLite read-only mode prevents accidental SQL mutations.
        path = Path(core.ORDERS_DB).resolve()
        uri = path.as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
                db.row_factory = sqlite3.Row
                sql = ("SELECT id, origin, destination, trip_date, trip_time, "
                       "status, price FROM orders")
                params = []
                if status:
                    sql += " WHERE status=?"
                    params.append(status)
                sql += " ORDER BY id DESC LIMIT ?"
                params.append(limit)
                rows = [dict(row) for row in db.execute(sql, params)]
        except sqlite3.Error:
            app.logger.exception("Read-only n8n orders query failed")
            return jsonify(error="Orders temporarily unavailable"), 503

        response = jsonify(orders=rows, count=len(rows))
        response.headers["Cache-Control"] = "private, no-store"
        return response
