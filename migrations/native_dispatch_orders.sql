BEGIN;
CREATE TABLE IF NOT EXISTS pd_dispatch_orders (
 id UUID PRIMARY KEY,
 source TEXT NOT NULL,
 source_order_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 origin TEXT NOT NULL,
 destination TEXT NOT NULL,
 trip_date TEXT NOT NULL,
 trip_time TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'requested'
   CHECK (status IN ('requested','assigned','approaching','underway','finished','cancelled')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(source,source_order_id)
);
CREATE TABLE IF NOT EXISTS pd_native_order_owners (
 order_id UUID PRIMARY KEY REFERENCES pd_dispatch_orders(id),
 user_id TEXT NOT NULL REFERENCES native_auth_users(id)
);
CREATE INDEX IF NOT EXISTS pd_native_order_owners_user ON pd_native_order_owners(user_id);
COMMIT;
