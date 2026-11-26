"""QA-only browser dispatcher map probe using the merged WSGI.

The process inherits only synthetic localhost PostgreSQL credentials from CI.
"""
import importlib
import json
import os
from pathlib import Path
import re
import sys
from werkzeug.security import generate_password_hash

def main():
    if len(sys.argv) != 2:
        raise SystemExit("expected synthetic order UUID")
    oid = sys.argv[1]
    assert os.environ["PD_DISPATCH_STAGING_ONLY"] == "1"
    assert os.environ["PD_PAYMENT_MODE"] == "disabled"
    assert os.environ["PD_NATIVE_SMS_LIVE"] == "NO"
    assert os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"].startswith(
        "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test")
    assert os.environ["PD_QA27_GPS"] == "1"
    password = "qa-merged-map-only-password"
    os.environ["PD_DISPATCH_PASSWORD_HASH"] = generate_password_hash(password,method="pbkdf2:sha256")
    os.environ.pop("PD_DISPATCH_DATABASE_URL",None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    module = importlib.import_module("pd_dispatcher_staging_wsgi")
    app = module.create_app()
    client = app.test_client()
    base = "https://localhost"
    gps = "/dispatch/orders/" + oid + "/gps"
    assert client.get(gps,base_url=base).status_code == 401
    assert client.get("/dispatch/map",base_url=base).status_code in (301,302,303)
    login_page = client.get("/dispatch/login",base_url=base)
    assert login_page.status_code == 200
    csrf = re.search(r'name="csrf" value="([^"]+)"',login_page.get_data(as_text=True))
    assert csrf
    login = client.post("/dispatch/login",data={"csrf":csrf.group(1),"password":password},base_url=base)
    assert login.status_code in (301,302,303)
    map_page = client.get("/dispatch/map",base_url=base)
    assert map_page.status_code == 200, map_page.get_data(as_text=True)[:1000]
    html=map_page.get_data(as_text=True)
    assert 'id="rasterMap"' in html
    assert '/dispatch/orders/' in html and '/gps' in html
    assert "refreshOrderGps" in html
    assert map_page.headers.get("Cache-Control") == "private, no-store"
    queue=client.get("/dispatch/orders/state",base_url=base)
    assert queue.status_code==200, queue.get_data(as_text=True)
    assert oid in [o["id"] for o in queue.json["orders"]]
    coordinates=client.get(gps,base_url=base)
    assert coordinates.status_code==200, coordinates.get_data(as_text=True)
    assert coordinates.json["available"] is True
    assert (coordinates.json["latitude"],coordinates.json["longitude"])==(54.6872,25.2797)
    # Fail closed at request time if QA-only GPS display is disabled.
    os.environ["PD_QA27_GPS"]="0"
    assert client.get(gps,base_url=base).status_code==503
    print(json.dumps({"map_loaded": True,"order_found": True,
        "gps_visible":True,"anonymous_denied":True,"disabled_fail_closed":True}))

if __name__=="__main__":
    main()
