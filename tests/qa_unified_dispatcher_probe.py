"""Browser dispatcher contract probe against pinned WSGI, in a separate process.

Only localhost synthetic PostgreSQL is permitted; browser authentication and
CSRF are exercised without bypassing the deployed dispatcher login handlers.
"""
import importlib
import json
import os
from pathlib import Path
import re
import sys
import uuid


def main():
    if len(sys.argv) != 3:
        raise ValueError("usage: probe <pinned-dispatcher-checkout> <order-map-json>")
    root = Path(sys.argv[1]).resolve()
    assert root.is_dir() and root.name == "dispatcher"
    order_sources = json.loads(sys.argv[2])
    assert len(order_sources) == 2
    assert set(order_sources.values()) == {"android", "telegram_miniapp"}
    assert all(str(uuid.UUID(oid)) == oid for oid in order_sources)
    assert os.environ["PD_DISPATCH_STAGING_ONLY"] == "1"
    assert os.environ["PD_PAYMENT_MODE"] == "disabled"
    assert os.environ["PD_NATIVE_SMS_LIVE"] == "NO"
    assert os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"].startswith(
        "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    )

    sys.path.insert(0, str(root))
    module = importlib.import_module("pd_dispatcher_staging_wsgi")
    assert Path(module.__file__).resolve() == root / "pd_dispatcher_staging_wsgi.py"
    app = module.create_app()
    client = app.test_client()
    base = "https://localhost"

    assert client.get("/dispatch/orders/state", base_url=base).status_code == 401
    for oid in order_sources:
        assert client.post("/dispatch/orders/" + oid + "/assign",
            data={"csrf": "wrong", "pilot_id": "unified-pilot"},
            base_url=base).status_code == 401

    login_page = client.get("/dispatch/login", base_url=base)
    assert login_page.status_code == 200
    csrf_match = re.search(r'name="csrf" value="([^"]+)"',
                           login_page.get_data(as_text=True))
    assert csrf_match, "missing dispatcher login CSRF"
    password = os.environ.pop("QA_UNIFIED_DISPATCH_PASSWORD")
    login = client.post("/dispatch/login", data={
        "csrf": csrf_match.group(1), "password": password
    }, base_url=base)
    assert login.status_code in (302, 303), login.get_data(as_text=True)[:120]
    with client.session_transaction(base_url="https://localhost/dispatch") as session:
        assert session["pd_dispatch_authenticated"] is True
        csrf = session["pd_dispatch_csrf"]

    initial = client.get("/dispatch/orders/state", base_url=base)
    assert initial.status_code == 200, initial.get_data(as_text=True)
    rows = {order["id"]: order for order in initial.json["orders"]}
    assert order_sources.keys() <= rows.keys()
    for oid, source in order_sources.items():
        assert rows[oid]["source"] == source
        assert rows[oid]["status"] == "requested"

    candidates = client.get("/dispatch/orders/eligible-pilots", base_url=base)
    assert candidates.status_code == 200, candidates.get_data(as_text=True)
    assert "unified-pilot" in {p["id"] for p in candidates.json["pilots"]}
    for oid in order_sources:
        path = "/dispatch/orders/" + oid + "/assign"
        assert client.post(path, data={
            "csrf": "incorrect", "pilot_id": "unified-pilot"
        }, base_url=base).status_code == 403
        assign = client.post(path, data={
            "csrf": csrf, "pilot_id": "unified-pilot"
        }, base_url=base)
        assert assign.status_code == 200, assign.get_data(as_text=True)
        assert assign.json["changed"] is True and assign.json["status"] == "assigned"
        repeat = client.post(path, data={
            "csrf": csrf, "pilot_id": "unified-pilot"
        }, base_url=base)
        assert repeat.status_code == 200 and repeat.json["changed"] is False

    final = client.get("/dispatch/orders/state", base_url=base)
    assert final.status_code == 200
    updated = {order["id"]: order for order in final.json["orders"]}
    assert all(updated[oid]["status"] == "assigned" for oid in order_sources)
    print(json.dumps({
        "orders": {oid: {"source": source, "status": updated[oid]["status"]}
                   for oid, source in order_sources.items()},
        "pilot": "unified-pilot", "browser_login": "verified",
        "csrf": "verified", "assignment_idempotent": True
    }, sort_keys=True))


if __name__ == "__main__":
    main()
