"""Owner-only read model of approved pilots and their active trip positions."""
import time


def register_live_pilots(app, core, authorized):
    @app.get("/dispatch/live/pilots")
    def live_pilots():
        headers = {"Cache-Control": "private, no-store"}
        if not authorized():
            return {"error": "unauthorized"}, 401, headers
        try:
            with core.db(core.ORDERS_DB) as orders:
                trips = orders.execute("""
                    SELECT a.pilot_id, o.id AS order_id, o.status,
                           t.lat, t.lon, t.location_at
                    FROM pd_pilot_assignments a JOIN orders o ON o.id=a.order_id
                    LEFT JOIN pd_trip_runtime_v4 t ON t.order_id=o.id
                        AND t.location_pilot_id=a.pilot_id AND t.ended_at IS NULL
                    WHERE o.status IN ('Подтверждена','В пути')
                    ORDER BY t.location_at DESC, o.id DESC
                """).fetchall()
            with core.db(core.USERS_DB) as users:
                approved = users.execute("""
                    SELECT telegram_id, name, vehicle, plate, phone
                    FROM pd_driver_applications WHERE status='approved' ORDER BY name
                """).fetchall()
            latest = {}
            for row in trips:
                latest.setdefault(row["pilot_id"], dict(row))
            items = [dict(dict(pilot), trip=latest.get(pilot["telegram_id"])) for pilot in approved]
            return {"pilots": items, "now": int(time.time())}, 200, headers
        except Exception as exc:
            app.logger.error("Live pilot data unavailable (%s)", type(exc).__name__)
            return {"error": "pilot_data_unavailable"}, 503, headers
