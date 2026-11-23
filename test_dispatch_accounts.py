"""Security tests for the PRIVATE DRIVE staging dispatcher user registry."""
import os
import unittest
from unittest.mock import patch
from flask import Flask

from pd_dispatch_accounts import (
    REQUIRED_TABLES, mask_phone, registry_data, register,
)
from pd_unified_accounts_schema import safe_dispatcher_registry_sql


class DummyCursor:
    def __init__(self, migrated=True, accounts=()):
        self.migrated=migrated
        self.accounts=accounts
        self.last_sql=""
        self.execute_count=0

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, args=None):
        self.last_sql=sql
        self.execute_count += 1
        if self.execute_count == 1:
            assert args and set(args[0])==REQUIRED_TABLES
        else:
            assert sql == safe_dispatcher_registry_sql()
    def fetchall(self):
        if self.execute_count == 1:
            names=REQUIRED_TABLES if self.migrated else {"native_auth_users"}
            return [(name,) for name in names]
        return self.accounts


class DummyConn:
    def __init__(self, cur):
        self.cur=cur
    def __enter__(self):return self
    def __exit__(self, *_):return False
    def cursor(self):return self.cur


class DispatcherAccountRegistryTests(unittest.TestCase):
    def make_app(self, authorized=False, enabled=False, migrated=True, accounts=()):
        app=Flask(__name__)
        cur=DummyCursor(migrated, accounts)
        register(app, lambda: authorized, lambda: DummyConn(cur))
        app.testing=True
        env={"PD_DISPATCH_STAGING_ONLY":"1","PD_DISPATCH_REGISTRY_ENABLED":"1"} if enabled else {}
        return app.test_client(), env, cur

    def test_unauthenticated_user_never_queries_database(self):
        c, env, cur = self.make_app(authorized=False, enabled=True)
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(c.get("/dispatch/accounts").status_code,401)
            self.assertEqual(c.get("/dispatch/accounts/state").status_code,401)
        self.assertEqual(cur.execute_count,0)

    def test_registry_is_disabled_without_explicit_stage_gate(self):
        c, env, cur=self.make_app(authorized=True,enabled=False)
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(c.get("/dispatch/accounts/state").status_code,503)
        self.assertEqual(cur.execute_count,0)

    def test_migration_missing_is_fail_closed(self):
        c, env, cur=self.make_app(authorized=True,enabled=True,migrated=False)
        with patch.dict(os.environ,env,clear=True):
            res=c.get("/dispatch/accounts/state")
        self.assertEqual(res.status_code,503)
        self.assertEqual(res.json["error"],"registry_migration_required")
        self.assertEqual(cur.execute_count,1)

    def test_authorized_registry_masks_phones_and_no_private_blobs(self):
        row_passenger=("p1","passenger","Тест пассажир","+37060000123",False,None)
        row_pilot=("p2","pilot",None,"+37060000456",True,"pending")
        c, env, cur=self.make_app(authorized=True,enabled=True,accounts=(row_passenger,row_pilot))
        with patch.dict(os.environ,env,clear=True):
            r=c.get("/dispatch/accounts/state")
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers["Cache-Control"],"private, no-store")
        self.assertEqual(len(r.json["accounts"]),2)
        self.assertTrue(r.json["read_only"])
        self.assertEqual(r.json["accounts"][1]["pilot_review_label"],"На проверке")
        self.assertNotIn("+37060000123",r.get_data(as_text=True))
        self.assertNotIn("+37060000456",r.get_data(as_text=True))
        for key in ("token_hash","photo","documents","encrypted_bytes","access_token"):
            self.assertNotIn(key,r.get_data(as_text=True))
        self.assertEqual(cur.execute_count,2)

    def test_masking_is_defensive(self):
        self.assertEqual(mask_phone("+37060000123"),"+37••••23")
        self.assertEqual(mask_phone(None),"Не указан")


if __name__=="__main__":
    unittest.main()
