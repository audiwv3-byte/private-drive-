"""Tests for the isolated n8n read-only API (no production database needed)."""
import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
import pd_n8n_readonly

class ReadonlyOrdersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "orders.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute('BEGIN')
            db.execute("CREATE TABLE orders (id INTEGER, origin TEXT, destination TEXT, trip_date TEXT, trip_time TEXT, status TEXT, price REAL, telegram_id INTEGER, payment_method TEXT)")
            db.execute("INSERT INTO orders VALUES (1,'Vilnius','Kaunas','01.12.2026','10:00','Новая',130,12345,'cash')")
        self.app = Flask(__name__)
        pd_n8n_readonly.register(self.app, SimpleNamespace(ORDERS_DB=path))
        self.client = self.app.test_client()
        self.secret = "a" * 48
        self.patch = patch.dict(os.environ, {"PD_N8N_READONLY_TOKEN": self.secret})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_unauthorized(self):
        self.assertEqual(self.client.get("/api/integrations/n8n/orders").status_code, 401)
        self.assertEqual(self.client.get("/api/integrations/n8n/orders",headers={"Authorization":"Bearer incorrect"}).status_code,401)

    def test_fail_closed_when_not_configured(self):
        with patch.dict(os.environ, {"PD_N8N_READONLY_TOKEN": ""}):
            self.assertEqual(self.client.get("/api/integrations/n8n/orders",headers={"Authorization":"Bearer "+self.secret}).status_code,401)

    def test_authorized_minimal_read(self):
        r=self.client.get("/api/integrations/n8n/orders?limit=1",headers={"Authorization":"Bearer "+self.secret})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json["count"],1)
        self.assertEqual(set(r.json["orders"][0]),{"id","origin","destination","trip_date","trip_time","status","price"})
        self.assertEqual(r.headers["Cache-Control"],"private, no-store")

    def test_limit_and_status_validation(self):
        h={"Authorization":"Bearer "+self.secret}
        self.assertEqual(self.client.get("/api/integrations/n8n/orders?limit=500",headers=h).status_code,400)
        self.assertEqual(self.client.get("/api/integrations/n8n/orders?status=invalid",headers=h).status_code,400)
        self.assertEqual(self.client.get("/api/integrations/n8n/orders?status=Отменена",headers=h).json["count"],0)

if __name__=="__main__":
    unittest.main()
