"""Offline isolation checks extracted from real production handlers; no customer DB."""
import ast
import contextlib
import pathlib
import sqlite3
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = (ROOT / "miniapp_server.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

def extract_function(name, env):
    target = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    target = ast.FunctionDef(
        name=target.name, args=target.args, body=target.body,
        decorator_list=[], returns=target.returns, type_comment=None,
    )
    ast.fix_missing_locations(target)
    exec(compile(ast.Module(body=[target], type_ignores=[]), "isolated_source", "exec"), env)
    return env[name]

class FakeHeaders(dict):
    pass

class FakeResponse:
    def __init__(self):
        self.headers = FakeHeaders()
        self.vary = set()

class Isolation(unittest.TestCase):
    def test_all_private_api_paths_no_cache(self):
        req = types.SimpleNamespace(path="")
        fn = extract_function("private_response_cache", {"request": req})
        for path in ("/api/orders", "/api/trip/42", "/api/driver/work",
                     "/api/admin/orders", "/api/me", "/api/payment/42"):
            req.path = path
            response = fn(FakeResponse())
            self.assertIn("no-store", response.headers["Cache-Control"], path)
            self.assertEqual(response.headers["Pragma"], "no-cache", path)
            self.assertEqual(response.headers["Expires"], "0", path)
            self.assertIn("X-Telegram-Init-Data", response.vary, path)

    def test_passengers_cannot_list_each_others_orders(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE orders (
          id INTEGER PRIMARY KEY, telegram_id INTEGER,
          origin TEXT,destination TEXT,trip_date TEXT,trip_time TEXT,
          status TEXT,price TEXT,payment_method TEXT,payment_status TEXT)""")
        for id_,uid in ((101,111),(202,222)):
            conn.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (id_,uid,"A","B","07.11.2026","18:30",
                          "Подтверждена","200.00","Наличные","Оплачено"))
        user = {"id": 111}
        core = types.SimpleNamespace(ORDERS_DB="memory", db=lambda _: contextlib.nullcontext(conn))
        fn = extract_function("orders", {
            "auth": lambda: (user["id"], {}),
            "core": core,
            "jsonify": lambda **kwargs: kwargs,
        })
        first = fn()["orders"]
        self.assertEqual([r["id"] for r in first], [101])
        user["id"] = 222
        second = fn()["orders"]
        self.assertEqual([r["id"] for r in second], [202])
        self.assertFalse({r["id"] for r in first} & {r["id"] for r in second})
        conn.close()

    def test_trip_id_authorization_exists(self):
        src = (ROOT / "pd_trip_runtime_v4.py").read_text(encoding="utf-8")
        self.assertIn("uid not in (r['telegram_id'], r['pilot_id'])", src)
        self.assertIn("raise PermissionError('Нет доступа к поездке')", src)

if __name__ == "__main__":
    unittest.main()
