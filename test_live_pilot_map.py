import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

from pd_dispatcher_production_wsgi import read_orders
from pd_live_pilot_map import register_live_pilots


class LivePilotMapTest(unittest.TestCase):
    def test_two_pilots_reassignment_and_closed_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            core = SimpleNamespace(ORDERS_DB=path/'orders.db', USERS_DB=path/'users.db', db=read_orders)
            with sqlite3.connect(core.USERS_DB) as db:
                db.executescript("""
                    CREATE TABLE pd_driver_applications(telegram_id, name, vehicle, plate, phone, status);
                    INSERT INTO pd_driver_applications VALUES
                        (1,'A','','QA1','','approved'),(2,'B','','QA2','','approved'),
                        (3,'C','','QA3','','pending');
                """)
            with sqlite3.connect(core.ORDERS_DB) as db:
                db.executescript("""
                    CREATE TABLE orders(id,status);
                    CREATE TABLE pd_pilot_assignments(order_id,pilot_id);
                    CREATE TABLE pd_trip_runtime_v4(order_id, location_pilot_id,lat,lon,location_at,ended_at);
                    INSERT INTO orders VALUES(10,'В пути'),(20,'Подтверждена');
                    INSERT INTO pd_pilot_assignments VALUES(10,1),(20,2);
                    INSERT INTO pd_trip_runtime_v4 VALUES(10,1,54,25,100,NULL),(20,2,55,26,200,NULL);
                """)
            app = Flask(__name__)
            owner = False
            register_live_pilots(app, core, lambda: owner)
            client = app.test_client()
            self.assertEqual(client.get('/dispatch/live/pilots').status_code, 401)
            owner = True
            url = '/dispatch/live/pilots'
            pilots = client.get(url).json['pilots']
            self.assertEqual([p['trip']['lat'] for p in pilots], [54,55])
            with sqlite3.connect(core.ORDERS_DB) as db:
                db.execute("UPDATE orders SET status='Выполнена' WHERE id=10")
                db.execute("UPDATE pd_pilot_assignments SET pilot_id=1 WHERE order_id=20")
            pilots = client.get(url).json['pilots']
            self.assertIsNone(pilots[0]['trip']['lat'])
            self.assertIsNone(pilots[1]['trip'])
