CREATE TABLE IF NOT EXISTS public.pd_qa_telegram_candidates (
    telegram_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    city TEXT NOT NULL,
    vehicle TEXT NOT NULL,
    vehicle_year INTEGER NOT NULL,
    plate TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    updated_at TIMESTAMPTZ NOT NULL
);
