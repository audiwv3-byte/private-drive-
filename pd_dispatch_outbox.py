"""Durable staging outbox; run explicitly as a separate worker."""
import json
import sqlite3
import time
import os
from pd_telegram_persistent_bridge import enabled, deliver, DeliveryError

def enqueue(conn, order):
    conn.execute("""CREATE TABLE IF NOT EXISTS pd_dispatch_outbox
        (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
         next_attempt REAL NOT NULL DEFAULT 0, delivered INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("INSERT OR IGNORE INTO pd_dispatch_outbox(id,payload) VALUES (?,?)",
                 (order["id"],json.dumps(order,ensure_ascii=False)))

def drain(conn, *, sender=deliver, now=time.time):
    if not enabled():
        return 0
    rows=conn.execute("SELECT id,payload,attempts FROM pd_dispatch_outbox WHERE delivered=0 AND next_attempt<=? ORDER BY id LIMIT 50",(now(),)).fetchall()
    for oid,payload,attempts in rows:
        try:
            sender(json.loads(payload))
        except DeliveryError:
            conn.execute("UPDATE pd_dispatch_outbox SET attempts=attempts+1,next_attempt=? WHERE id=? AND delivered=0",(now()+min(3600,2**min(attempts+1,12)),oid))
        else:
            conn.execute("UPDATE pd_dispatch_outbox SET delivered=1 WHERE id=?",(oid,))
        conn.commit()
    return len(rows)

def main():
    if not enabled() or os.getenv("PD_OUTBOX_WORKER")!="1":
        raise SystemExit("isolated worker disabled")
    path=os.environ["PD_OUTBOX_SQLITE_PATH"]
    while True:
        with sqlite3.connect(path,timeout=10) as conn:
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pd_dispatch_outbox'").fetchone()
            if exists:
                drain(conn)
        time.sleep(5)

if __name__=="__main__":
    main()
