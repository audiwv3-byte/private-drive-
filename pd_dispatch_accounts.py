"""Read-only unified dispatcher registry (staging only, fail closed).

Requires explicit database migration and PD_DISPATCH_REGISTRY_ENABLED=1.
Only uses the existing authenticated browser dispatcher session. Never sends
identity photos, OTP challenges, session tokens or document bytes to browser.
"""
import os

from flask import Response, jsonify

from pd_unified_accounts_schema import PILOT_LABELS, safe_dispatcher_registry_sql

REQUIRED_TABLES = frozenset({
    "native_auth_users", "native_auth_roles", "pd_account_profiles",
    "pd_account_telegram_links", "pd_pilot_reviews",
})


def registry_enabled():
    return (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.environ.get("PD_DISPATCH_REGISTRY_ENABLED") == "1")


def mask_phone(phone):
    if not isinstance(phone, str) or len(phone) < 5:
        return "Не указан"
    return phone[:3] + "••••" + phone[-2:]


def registry_data(conn):
    """No DDL; fail closed until all reviewed migration tables exist."""
    with conn.cursor() as cur:
        cur.execute("""SELECT tablename FROM pg_catalog.pg_tables
                       WHERE schemaname='public' AND tablename=ANY(%s)""",
                    (sorted(REQUIRED_TABLES),))
        present = {row[0] for row in cur.fetchall()}
        if not REQUIRED_TABLES.issubset(present):
            raise RuntimeError("registry_migration_required")
        cur.execute(safe_dispatcher_registry_sql())
        rows = cur.fetchall()
    records = []
    for user_id, role, display_name, phone, tg_linked, review_status in rows:
        is_pilot = role == "pilot" or review_status is not None
        effective_status = (review_status or "pending") if is_pilot else None
        records.append({
            "user_id": user_id,
            "role": role if role in ("passenger", "pilot", "admin") else "passenger",
            "name": display_name or "Без имени",
            "phone_masked": mask_phone(phone),
            "telegram_linked": bool(tg_linked),
            "pilot_review_status": effective_status,
            "pilot_review_label": PILOT_LABELS.get(effective_status)
                                   if effective_status else None,
        })
    return records


def register(app, authorized, connect):
    """Pass the same authorized() callback as /dispatch/map."""
    def respond(data, status):
        res = jsonify(data)
        res.status_code = status
        res.headers["Cache-Control"] = "private, no-store"
        res.headers["X-Content-Type-Options"] = "nosniff"
        res.headers["Referrer-Policy"] = "no-referrer"
        return res

    @app.get("/dispatch/accounts/state")
    def dispatch_accounts_state():
        if not authorized():
            return respond({"error": "unauthorized"}, 401)
        if not registry_enabled() or not callable(connect):
            return respond({"error": "registry_disabled"}, 503)
        try:
            with connect() as conn:
                records = registry_data(conn)
        except RuntimeError as exc:
            if str(exc) == "registry_migration_required":
                return respond({"error": "registry_migration_required"}, 503)
            app.logger.warning("Registry unavailable: %s", type(exc).__name__)
            return respond({"error": "registry_unavailable"}, 503)
        except Exception as exc:
            app.logger.warning("Registry unavailable: %s", type(exc).__name__)
            return respond({"error": "registry_unavailable"}, 503)
        return respond({"accounts": records, "read_only": True}, 200)

    @app.get("/dispatch/accounts")
    def dispatch_accounts_page():
        if not authorized():
            return respond({"error": "unauthorized"}, 401)
        page = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>PRIVATE DRIVE — пассажиры и пилоты</title>
<style>body{margin:0;background:#110f0c;color:#f2ece1;font:15px system-ui;padding:24px}
main{max-width:1000px;margin:auto}a,h1,h2{color:#e8c581}
article{padding:15px;margin:10px 0;background:#242019;border:1px solid #625036;border-radius:12px}
small{color:#c9bba3}nav{margin-bottom:20px}button{cursor:pointer}
[hidden]{display:none}</style></head><body><main>
<nav><a href="/dispatch/map">Диспетчерская</a></nav>
<h1>Пассажиры и пилоты</h1>
<p>Только чтение. Телефоны скрыты. Документы и токены здесь не отображаются.</p>
<p id="status" role="status">Проверяем доступ к реестру…</p>
<h2>Пассажиры</h2><section id="passengers"></section>
<h2>Пилоты</h2><section id="pilots"></section>
<script>
(async()=>{
  const status=document.getElementById('status');
  try{
    const response=await fetch('/dispatch/accounts/state',{credentials:'same-origin',cache:'no-store'});
    const data=await response.json();
    if(!response.ok)throw Error(data.error==='registry_migration_required'?
      'Безопасная миграция ещё не применена.':
      'Реестр пока закрыт.');
    let passengers=0,pilots=0;
    for(const account of data.accounts){
      const pilot=account.role==='pilot'||account.pilot_review_status!==null;
      const section=document.getElementById(pilot?'pilots':'passengers');
      const card=document.createElement('article');
      for(const item of [
        account.name,account.phone_masked,
        'Роль: '+account.role,
        pilot?'Проверка: '+account.pilot_review_label:''
      ]){
        if(!item)continue;
        const p=document.createElement('p');p.textContent=item;card.append(p);
      }
      section.append(card); if(pilot)pilots++;else passengers++;
    }
    status.textContent='Пассажиры: '+passengers+' · Пилоты: '+pilots;
  }catch(error){status.textContent=error.message;}
})();
</script></main></body></html>"""
        return Response(page, content_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "private, no-store",
                                 "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer",
                                 "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})
