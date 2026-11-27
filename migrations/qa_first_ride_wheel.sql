BEGIN;
DO $$
BEGIN
    IF current_database() <> 'private_drive_test' THEN
        RAISE EXCEPTION 'First-ride wheel requires the isolated test database';
    END IF;
END
$$;

ALTER TABLE public.pd_account_telegram_links
    DROP CONSTRAINT IF EXISTS pd_account_telegram_links_verification_method_check;
ALTER TABLE public.pd_account_telegram_links
    ADD CONSTRAINT pd_account_telegram_links_verification_method_check
        CHECK (verification_method IN ('telegram_oidc', 'mini_app_phone_session'));

CREATE TABLE IF NOT EXISTS public.pd_first_ride_rewards (
    user_id text PRIMARY KEY REFERENCES public.native_auth_users(id),
    percent smallint NOT NULL CHECK (percent IN (5, 10, 15, 20)),
    expires_at bigint NOT NULL,
    order_id uuid UNIQUE REFERENCES public.pd_dispatch_orders(id)
);
REVOKE ALL ON TABLE public.pd_first_ride_rewards FROM PUBLIC;
COMMIT;
