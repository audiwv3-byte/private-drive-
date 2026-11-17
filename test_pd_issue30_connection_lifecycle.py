"""PRIVATE DRIVE Issue #30: raw sqlite3 connection lifecycle, synthetic only."""
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from pd_issue30_connection import managed_core_db

class RawSqliteCore:
    USERS_DB = "fake"
    def __init__(self,path):
        self.path=path
        self.handles=[]
    def db(self,_):
        conn=sqlite3.connect(self.path)
        conn.execute("PRAGMA busy_timeout=10000")
        self.handles.append(conn)
        return conn

class ContextmanagerCore(RawSqliteCore):
    @contextmanager
    def db(self,_):
        conn=sqlite3.connect(self.path)
        self.handles.append(conn)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

class ConnectionLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="issue30-connection-")
        self.path=Path(self.temp.name)/"synthetic.db"
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE test_rows (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO test_rows VALUES (1,'initial')")
    def tearDown(self):
        self.temp.cleanup()
    def row(self):
        with sqlite3.connect(self.path) as c:
            return c.execute("SELECT value FROM test_rows WHERE id=1").fetchone()[0]
    def assert_closed(self,conn):
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_raw_live_style_commits_and_closes(self):
        core=RawSqliteCore(self.path)
        with managed_core_db(core) as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE test_rows SET value='accepted' WHERE id=1")
        self.assertEqual(self.row(),"accepted")
        self.assert_closed(core.handles[-1])

    def test_raw_live_style_rolls_back_and_closes(self):
        core=RawSqliteCore(self.path)
        with self.assertRaisesRegex(ValueError,"synthetic error"):
            with managed_core_db(core) as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE test_rows SET value='wrong' WHERE id=1")
                raise ValueError("synthetic error")
        self.assertEqual(self.row(),"initial")
        self.assert_closed(core.handles[-1])

    def test_generator_style_fake_core_commits_and_closes(self):
        core=ContextmanagerCore(self.path)
        with managed_core_db(core) as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE test_rows SET value='accepted' WHERE id=1")
        self.assertEqual(self.row(),"accepted")
        self.assert_closed(core.handles[-1])

    def test_generator_style_fake_core_rolls_back_and_closes(self):
        core=ContextmanagerCore(self.path)
        with self.assertRaisesRegex(RuntimeError,"rollback"):
            with managed_core_db(core) as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE test_rows SET value='wrong' WHERE id=1")
                raise RuntimeError("rollback")
        self.assertEqual(self.row(),"initial")
        self.assert_closed(core.handles[-1])

    def test_read_only_does_not_change_row_and_closes(self):
        core=RawSqliteCore(self.path)
        with managed_core_db(core) as c:
            self.assertEqual(c.execute("SELECT value FROM test_rows").fetchone()[0],"initial")
        self.assertEqual(self.row(),"initial")
        self.assert_closed(core.handles[-1])

    def test_failing_sqlite_insert_rolls_back_and_closes(self):
        core=RawSqliteCore(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            with managed_core_db(core) as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE test_rows SET value='wrong' WHERE id=1")
                c.execute("INSERT INTO test_rows VALUES(1,'duplicate')")
        self.assertEqual(self.row(),"initial")
        self.assert_closed(core.handles[-1])

if __name__=="__main__":
    unittest.main()
