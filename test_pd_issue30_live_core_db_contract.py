"""Issue 30: run exact deployed core.db() function against a synthetic SQLite DB.

GET requests only Python SOURCE. Extract just db AST, compile in memory, use a
temporary local database. No runtime production objects or production DB path.
"""
import ast
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

import requests

EXPECTED_SHA="bf45ff7b4e097e13c2c5d12e7d22df7d8e6c274ea073867299ecfcc8d1649462"


class LiveCoreDbSyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token="".join(os.environ.get("PA_API_TOKEN","").strip().split())
        if not token:
            raise RuntimeError("Missing read-only source API token")
        path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/Euro_Baltic_Transfer.py"
        url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(path,safe="/")
        resp=requests.get(url,headers={"Authorization":"Token "+token},timeout=35)
        resp.raise_for_status()
        if hashlib.sha256(resp.content).hexdigest()!=EXPECTED_SHA:
            raise RuntimeError("core.db source fingerprint changed")
        tree=ast.parse(resp.content.decode("utf-8"))
        fn=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="db"]
        if len(fn)!=1:
            raise RuntimeError("Unexpected core.db definition")
        # Exact deployed function only, with an isolated known sqlite3 binding.
        module=ast.fix_missing_locations(ast.Module(body=fn,type_ignores=[]))
        namespace={"sqlite3":sqlite3}
        exec(compile(module,"<core.db verified source function>","exec"),namespace)
        cls.db=staticmethod(namespace["db"])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="issue30-coredb-synthetic-")
        self.path=Path(self.tmp.name)/"synthetic.sqlite"
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE fake (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO fake VALUES (1,'original')")

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_live_core_db_rolls_back_failed_write_transaction(self):
        conn=self.db(self.path)
        try:
            with self.assertRaises(RuntimeError):
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("UPDATE fake SET value='bad' WHERE id=1")
                    raise RuntimeError("synthetic forced rollback")
        finally:
            conn.close()
        with sqlite3.connect(self.path) as check:
            self.assertEqual(check.execute("SELECT value FROM fake WHERE id=1").fetchone()[0],"original")

    def test_exact_live_core_db_commits_successful_transaction(self):
        conn=self.db(self.path)
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE fake SET value='changed' WHERE id=1")
        finally:
            conn.close()
        with sqlite3.connect(self.path) as check:
            self.assertEqual(check.execute("SELECT value FROM fake WHERE id=1").fetchone()[0],"changed")

    def test_exact_live_core_db_has_expected_timeout_and_row_factory(self):
        conn=self.db(self.path)
        try:
            self.assertIs(conn.row_factory,sqlite3.Row)
            timeout=conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(timeout,20000)
        finally:
            conn.close()

if __name__=="__main__":
    unittest.main()
