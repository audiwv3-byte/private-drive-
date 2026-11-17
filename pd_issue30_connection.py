"""Issue #30: transaction-safe, deterministic lifecycle for core.db.

The verified live core.db returns a raw sqlite3.Connection; entering
"with connection" commits/rolls back but does NOT close it. Synthetic fixtures
may instead return a contextmanager that closes its connection on __exit__.

This adapter supports both without altering core, database paths or any
existing transaction semantics. It neither starts transactions nor touches
production at import time.
"""
from contextlib import contextmanager


@contextmanager
def managed_core_db(core):
    handle = core.db(core.USERS_DB)
    try:
        with handle as conn:
            yield conn
    finally:
        close = getattr(handle, "close", None)
        if callable(close):
            close()
