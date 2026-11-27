import hashlib
import secrets
import ssl
import urllib.request
import urllib.error
import hmac
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import psycopg
from werkzeug.serving import make_server

from pd_native_auth_postgres_http import initialize_database
from ops.qa.qa42_local_kit import prepare


def test_local_kit(monkeypatch, tmp_path):
    monkeypatch.setenv("PD_QA42_LOCAL","YES")
    app,tokens,telegram_token,csrf = prepare()
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    c=Client(app,Response)
    for role in ("passenger","pilot"):
        response=c.post("/native-auth/session",headers={"Authorization":"Bearer "+tokens[role]})
        assert response.status_code==200
        assert response.json["role"]==role
    assert c.post("/native-auth/session").status_code==401
    assert c.post("/native-auth/request-code",json={}).status_code==503
    assert c.get("/payment/paysera").status_code==403
    assert c.get("/dispatch/orders/state").status_code==401
    import pytest
    with pytest.raises(RuntimeError,match="Fresh"):
        prepare()
    print("PASS local kit bootstrap, scoped sessions, blocked external services and fresh DB gate")
