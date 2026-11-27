BEGIN;
CREATE TABLE IF NOT EXISTS public.pd_qa_telegram_candidates (
    telegram_id bigint PRIMARY KEY,
    name text NOT NULL,
    phone text NOT NULL,
    city text NOT NULL,
    vehicle text NOT NULL,
    vehicle_year integer NOT NULL,
    plate text NOT NULL,
    seats integer NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS pd_qa_telegram_candidates_recent
    ON public.pd_qa_telegram_candidates (updated_at DESC, telegram_id DESC);
REVOKE ALL ON public.pd_qa_telegram_candidates FROM PUBLIC;
COMMIT;
