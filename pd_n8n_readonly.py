"""Read-only, narrowly scoped n8n orders view. Disabled unless configured."""
import hmac
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from flask import jsonify, request

def register(app, core):
    @app.get("/api/integrations/n8n/orders")
    def n8n_orders_readonly():
        expected = os.environ.get("PD_N8N_READONLY_TOKEN", "")
        supplied = request.headers.get("Authorization", "")
        # Fail closed if a unique, long-lived secret is not configured.
        if len(expected) < 32 or not supplied.startswith("Bearer "):
            return jsonify(error="Unauthorized"), 401
        if not hmac.compare_digest(supplied[7:].encode(), expected.encode()):
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
