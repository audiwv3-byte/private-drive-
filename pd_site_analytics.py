"""Consent-based, first-party website funnel for the dispatcher workspace."""
import re
from threading import Lock

from flask import Response, abort, redirect, render_template_string, request, url_for

ORIGIN = "https://privatedrive.lt"
PAGES = {"/", "/services.html", "/directions.html", "/order-map.html", "/documents.html"}
EVENTS = {"view", "booking", "telegram"}
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,47}")
VISIT = re.compile(r"[0-9a-f]{32}")
REPORT = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Воронка сайта — PRIVATE DRIVE</title>
<link rel="stylesheet" href="/assets/pd-black-gold.css">
<style>body{background:#14110d;color:#fff2d7;font:16px system-ui;padding:1rem}
main{max-width:1000px;margin:auto}a{color:#edcc86}
table{border-collapse:collapse;width:100%}th,td{padding:.55rem;text-align:left;border-bottom:1px solid #6e563b}
.wide{overflow:auto}li{margin:.5rem 0}</style>
<main><a href="/dispatch">← Диспетчерская</a><h1>Воронка сайта за 30 дней</h1>
<p>Учитываются визиты с согласием на аналитику. Открытие Telegram — переход, а не подтверждённый заказ.</p>
<ul><li>Визиты: {{ totals[0] }}</li><li>Просмотры страниц: {{ totals[1] }}</li>
<li>Открыли форму заказа: {{ totals[2] }}</li><li>Перешли в Telegram: {{ totals[3] }}</li></ul>
<h2>Источники и кампании</h2><div class="wide"><table>
<thead><tr><th>Источник</th><th>Кампания</th><th>Визиты</th></tr></thead>
<tbody>{% for row in sources %}<tr><td>{{ row[0] }}</td><td>{{ row[1] or '—' }}</td><td>{{ row[2] }}</td></tr>{% endfor %}</tbody>
</table></div><h2>Последние переходы</h2><div class="wide"><table>
<thead><tr><th>Время (UTC)</th><th>Визит</th><th>Страница</th><th>Действие</th></tr></thead>
<tbody>{% for row in steps %}<tr><td>{{ row[0].strftime('%d.%m %H:%M') }}</td><td>{{ row[1][:8] }}</td><td>{{ row[2] }}</td><td>{{ labels[row[3]] }}</td></tr>{% endfor %}</tbody>
</table></div></main></html>"""


def normalize(payload):
    if not isinstance(payload, dict):
        return None
    visit, page, event, source, campaign = (
        payload.get(key, "") for key in ("visit", "page", "event", "source", "campaign")
    )
    if (not all(isinstance(value, str) for value in (visit, page, event, source, campaign))
            or not VISIT.fullmatch(visit) or page not in PAGES or event not in EVENTS
            or not LABEL.fullmatch(source) or (campaign and not LABEL.fullmatch(campaign))
            or (event != "view" and page != "/order-map.html")):
        return None
    return visit, page, event, source.lower(), campaign.lower()


def register(app, authorized, connect):
    schema_lock = Lock()
    initialized = False

    def ensure_schema():
        nonlocal initialized
        with schema_lock:
            if initialized:
                return
            with connect() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(192784221, 25)")
                conn.execute("""CREATE TABLE IF NOT EXISTS pd_site_funnel (
                    visit text NOT NULL, page text NOT NULL, event text NOT NULL,
                    source text NOT NULL, campaign text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (visit, page, event))""")
                conn.execute("CREATE INDEX IF NOT EXISTS pd_site_funnel_created ON pd_site_funnel(created_at)")
            initialized = True

    @app.route("/site-events", methods=["POST", "OPTIONS"])
    def pd_site_event():
        if request.headers.get("Origin") != ORIGIN:
            abort(403)
        headers = {
            "Access-Control-Allow-Origin": ORIGIN,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Cache-Control": "no-store",
            "Vary": "Origin",
        }
        if request.method == "OPTIONS":
            return Response(status=204, headers=headers)
        if request.content_length is None or not 0 < request.content_length <= 1024:
            return Response(status=413, headers=headers)
        event = normalize(request.get_json(silent=True))
        if event is None:
            return Response(status=400, headers=headers)
        ensure_schema()
        with connect() as conn:
            conn.execute("""INSERT INTO pd_site_funnel(visit,page,event,source,campaign)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", event)
            conn.execute("DELETE FROM pd_site_funnel WHERE created_at < NOW() - INTERVAL '30 days'")
        return Response(status=204, headers=headers)

    @app.get("/dispatch/analytics")
    def pd_site_analytics():
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        ensure_schema()
        with connect() as conn:
            totals = conn.execute("""SELECT COUNT(DISTINCT visit),
                COUNT(*) FILTER (WHERE event='view'),
                COUNT(DISTINCT visit) FILTER (WHERE event='booking'),
                COUNT(DISTINCT visit) FILTER (WHERE event='telegram')
                FROM pd_site_funnel WHERE created_at >= NOW() - INTERVAL '30 days'""").fetchone()
            sources = conn.execute("""SELECT source, campaign, COUNT(DISTINCT visit) AS visits
                FROM pd_site_funnel WHERE created_at >= NOW() - INTERVAL '30 days'
                GROUP BY source, campaign ORDER BY visits DESC, source, campaign LIMIT 50""").fetchall()
            steps = conn.execute("""SELECT created_at AT TIME ZONE 'UTC', visit, page, event
                FROM pd_site_funnel WHERE created_at >= NOW() - INTERVAL '30 days'
                ORDER BY created_at DESC LIMIT 100""").fetchall()
        return Response(render_template_string(REPORT, totals=totals, sources=sources, steps=steps,
                        labels={"view":"Просмотр", "booking":"Форма заказа", "telegram":"Переход в Telegram"}),
                        content_type="text/html; charset=utf-8",
                        headers={"Cache-Control":"private, no-store", "X-Robots-Tag":"noindex",
                                 "Content-Security-Policy":"default-src 'none'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"})
