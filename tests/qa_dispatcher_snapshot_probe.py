"""Read-only check of the pinned dispatcher WSGI against synthetic PostgreSQL.

Called by the isolated end-to-end test in a separate Python interpreter so the
deployed dispatcher imports its own pinned modules, not the QA native API ones.
"""
import importlib
import json
import os
from pathlib import Path
import re
import sys

def main():
    if len(sys.argv) != 3:
        raise RuntimeError("expected pinned checkout and synthetic order UUID")
    root = Path(sys.argv[1]).resolve()
    assert root.is_dir() and root.name == "dispatcher"
    assert os.environ["PD_DISPATCH_STAGING_ONLY"] == "1"
    assert os.environ["PD_PAYMENT_MODE"] == "disabled"
    assert os.environ["PD_NATIVE_SMS_LIVE"] == "NO"
    assert "127.0.0.1:5432/private_drive_test" in os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"]

    sys.path.insert(0, str(root))
    dispatcher = importlib.import_module("pd_dispatcher_staging_wsgi")
    assert Path(dispatcher.__file__).resolve() == root / "pd_dispatcher_staging_wsgi.py"
    app = dispatcher.create_app()
    client = app.test_client()
    base = "https://localhost"

    # A passenger cannot view the queue or assign drivers.
    assert client.get("/dispatch/orders/state", base_url=base).status_code == 401
    assert client.post("/dispatch/orders/" + sys.argv[2] + "/assign",
                       data={"pilot_id":"e2e-pilot","csrf":"bad"},base_url=base).status_code == 401

    # Exercise the actual browser login and CSRF rather than injecting an admin session.
    login_page = client.get("/dispatch/login", base_url=base)
    assert login_page.status_code == 200
    csrf_match = re.search(r'name="csrf" value="([^"]+)"', login_page.get_data(as_text=True))
    assert csrf_match, "dispatcher login CSRF token missing"
    password = os.environ.pop("QA_DISPATCH_TEST_PASSWORD")
    login = client.post("/dispatch/login", data={"csrf":csrf_match.group(1), "password":password},
                        base_url=base)
    assert login.status_code in (302, 303), login.get_data(as_text=True)[:150]
    with client.session_transaction(base_url="https://localhost/dispatch") as session:
        csrf = session["pd_dispatch_csrf"]
        assert session["pd_dispatch_authenticated"] is True

    queue = client.get("/dispatch/orders/state", base_url=base)
    assert queue.status_code == 200, queue.get_data(as_text=True)
    orders = {o["id"]:o for o in queue.json["orders"]}
    assert sys.argv[2] in orders
    assert orders[sys.argv[2]]["source"] == "android"
    assert orders[sys.argv[2]]["status"] == "requested"

    pilots = client.get("/dispatch/orders/eligible-pilots", base_url=base)
    assert pilots.status_code == 200, pilots.get_data(as_text=True)
    assert "e2e-pilot" in {p["id"] for p in pilots.json["pilots"]}
    url = "/dispatch/orders/" + sys.argv[2] + "/assign"
    wrong_csrf = client.post(url, data={"pilot_id":"e2e-pilot", "csrf":"wrong"},base_url=base)
    assert wrong_csrf.status_code == 403
    assigned = client.post(url, data={"pilot_id":"e2e-pilot","csrf":csrf},base_url=base)
    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    assert assigned.json["changed"] is True
    repeat = client.post(url,data={"pilot_id":"e2e-pilot","csrf":csrf},base_url=base)
    assert repeat.status_code == 200 and repeat.json["changed"] is False
    final = client.get("/dispatch/orders/state",base_url=base)
    assert final.status_code == 200
    updated = {o["id"]:o for o in final.json["orders"]}
    assert updated[sys.argv[2]]["status"] == "assigned"
    print(json.dumps({"order_id":sys.argv[2], "source":"android",
                      "status":"assigned", "pilot":"e2e-pilot",
                      "browser_login":True, "csrf_checked":True,
                      "replay_idempotent":True}))

if __name__ == "__main__":
    main()
