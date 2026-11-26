-- Apply only to the isolated beta database, after the native session/order migrations.
-- Nothing here runs from an HTTP request. Grant only the named wrappers to runtime roles.
BEGIN;

DO $$
BEGIN
    IF current_database() <> 'private_drive_test' THEN
        RAISE EXCEPTION 'pilot assignment migration requires the isolated test database';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.pd_telegram_order_owners (
    order_id uuid PRIMARY KEY REFERENCES public.pd_dispatch_orders(id),
    telegram_id bigint NOT NULL CHECK (telegram_id > 0)
);
CREATE INDEX IF NOT EXISTS pd_telegram_order_owners_uid ON public.pd_telegram_order_owners(telegram_id);
REVOKE ALL ON TABLE public.pd_telegram_order_owners FROM PUBLIC;

CREATE TABLE IF NOT EXISTS public.pd_native_order_assignments (
    order_id uuid PRIMARY KEY REFERENCES public.pd_dispatch_orders(id),
    pilot_user_id text NOT NULL REFERENCES public.native_auth_users(id),
    assigned_by text NOT NULL CHECK (assigned_by ~ '^[1-9][0-9]{0,17}$'),
    assigned_at timestamptz NOT NULL DEFAULT statement_timestamp()
);
CREATE INDEX IF NOT EXISTS pd_native_order_assignments_pilot
    ON public.pd_native_order_assignments(pilot_user_id);

-- Require an actual pilot entitlement (not a generic admin privilege) and
-- the latest current photo review. Do not grant direct table or photo access.
CREATE OR REPLACE FUNCTION public.pd_pilot_assignment_is_eligible(
    candidate text, observed_at bigint
) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.native_auth_roles r
        CROSS JOIN LATERAL (
            SELECT i.status, i.decided_at
            FROM public.native_identity_checks i
            WHERE i.user_id = r.user_id
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT 1
        ) review
        WHERE r.user_id = candidate AND r.role IN ('pilot','pilot_dispatcher')
          AND review.status = 'approved'
          AND review.decided_at <= observed_at
          AND review.decided_at > observed_at - 604800
    )
$$;

CREATE OR REPLACE FUNCTION public.pd_pilot_assignment_candidates(observed_at bigint)
RETURNS TABLE(pilot_user_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
    SELECT r.user_id FROM public.native_auth_roles r
    WHERE r.role IN ('pilot','pilot_dispatcher')
      AND public.pd_pilot_assignment_is_eligible(r.user_id, observed_at)
    ORDER BY r.user_id LIMIT 100
$$;

CREATE OR REPLACE FUNCTION public.pd_assign_native_order(
    target_order uuid, target_pilot text, dispatcher_id text, observed_at bigint
) RETURNS TABLE(outcome text, resulting_status text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    current_status text;
    assigned_pilot text;
BEGIN
    IF dispatcher_id IS NULL OR dispatcher_id !~ '^[1-9][0-9]{0,17}$' THEN
        RETURN QUERY SELECT 'invalid_dispatcher'::text, NULL::text;
        RETURN;
    END IF;

    -- Native and Telegram orders require their owner record. Website bookings require
    -- the contact captured by the website handler. Lock the same status row that
    -- their history reads; concurrent assignments cannot both be accepted.
    SELECT o.status INTO current_status
    FROM public.pd_dispatch_orders o
    WHERE o.id = target_order AND (EXISTS (SELECT 1 FROM public.pd_native_order_owners n WHERE n.order_id=o.id)
        OR EXISTS (SELECT 1 FROM public.pd_telegram_order_owners t WHERE t.order_id=o.id)
        OR (o.source='website' AND o.website_contact IS NOT NULL)) FOR UPDATE OF o;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'order_not_found'::text, NULL::text;
        RETURN;
    END IF;

    IF NOT public.pd_pilot_assignment_is_eligible(target_pilot, observed_at) THEN
        RETURN QUERY SELECT 'pilot_not_eligible'::text, NULL::text;
        RETURN;
    END IF;

    SELECT a.pilot_user_id INTO assigned_pilot FROM public.pd_native_order_assignments a
    WHERE a.order_id = target_order;
    IF FOUND AND assigned_pilot = target_pilot THEN
        RETURN QUERY SELECT 'already_assigned'::text, current_status;
        RETURN;
    END IF;
    IF assigned_pilot IS NOT NULL OR current_status <> 'requested' THEN
        RETURN QUERY SELECT 'assignment_conflict'::text, current_status;
        RETURN;
    END IF;

    INSERT INTO public.pd_native_order_assignments (order_id, pilot_user_id, assigned_by)
        VALUES (target_order, target_pilot, dispatcher_id);
    UPDATE public.pd_dispatch_orders o SET status = 'assigned' WHERE o.id = target_order;
    RETURN QUERY SELECT 'assigned'::text, 'assigned'::text;
END
$$;

-- The native API role passes a session digest, not an arbitrary pilot ID.
-- Foreign or revoked sessions cannot read another pilot's order.
CREATE OR REPLACE FUNCTION public.pd_native_pilot_order_state(
    supplied_digest text, observed_at bigint
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    principal record;
    result jsonb;
BEGIN
    SELECT * INTO principal
    FROM public.pd_validate_native_session(supplied_digest, observed_at);
    IF NOT FOUND THEN RETURN jsonb_build_object('error','invalid_session'); END IF;
    IF principal.server_role NOT IN ('pilot','pilot_dispatcher') THEN
        RETURN jsonb_build_object('error','pilot_required');
    END IF;
    IF NOT public.pd_pilot_assignment_is_eligible(principal.user_id, observed_at) THEN
        RETURN jsonb_build_object('error','identity_approval_required');
    END IF;

    SELECT coalesce(jsonb_agg(to_jsonb(rows)), '[]'::jsonb) INTO result FROM (
        SELECT o.id AS order_id, o.origin AS "from", o.destination AS "to", o.trip_date,
               o.trip_time, o.status
        FROM public.pd_native_order_assignments a
        JOIN public.pd_dispatch_orders o ON o.id = a.order_id
        WHERE a.pilot_user_id = principal.user_id
          AND o.status IN ('assigned','approaching','underway')
        ORDER BY a.assigned_at DESC, o.id
        LIMIT 100
    ) rows;
    RETURN jsonb_build_object('orders', result, 'payment_mode', 'disabled');
END
$$;

REVOKE ALL ON TABLE public.pd_native_order_assignments FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_pilot_assignment_is_eligible(text,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_pilot_assignment_candidates(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_assign_native_order(uuid,text,text,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_native_pilot_order_state(text,bigint) FROM PUBLIC;
-- Trip transitions serialize on the shared order row and require the current assigned pilot.
CREATE OR REPLACE FUNCTION public.pd_native_pilot_trip_action(
    supplied_digest text, target_order text, action text, observed_at bigint
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    principal record;
    current_status text;
    expected_status text;
    next_status text;
BEGIN
    SELECT * INTO principal FROM public.pd_validate_native_session(supplied_digest, observed_at);
    IF NOT FOUND THEN RETURN jsonb_build_object('error','invalid_session'); END IF;
    IF principal.server_role NOT IN ('pilot','pilot_dispatcher')
       OR NOT public.pd_pilot_assignment_is_eligible(principal.user_id, observed_at) THEN
        RETURN jsonb_build_object('error','pilot_required');
    END IF;
    CASE action
      WHEN 'approach' THEN expected_status := 'assigned'; next_status := 'approaching';
      WHEN 'start' THEN expected_status := 'approaching'; next_status := 'underway';
      WHEN 'finish' THEN expected_status := 'underway'; next_status := 'finished';
      ELSE RETURN jsonb_build_object('error','invalid_action');
    END CASE;
    SELECT o.status INTO current_status FROM public.pd_dispatch_orders o
    JOIN public.pd_native_order_assignments a ON a.order_id=o.id
    WHERE o.id=target_order::uuid AND a.pilot_user_id=principal.user_id
    FOR UPDATE OF o;
    IF NOT FOUND THEN RETURN jsonb_build_object('error','order_not_found'); END IF;
    IF current_status=next_status THEN
        RETURN jsonb_build_object('order_id',target_order,'status',current_status,'changed',false,'payment_mode','disabled');
    END IF;
    IF current_status<>expected_status THEN RETURN jsonb_build_object('error','invalid_transition'); END IF;
    UPDATE public.pd_dispatch_orders SET status=next_status WHERE id=target_order::uuid;
    RETURN jsonb_build_object('order_id',target_order,'status',next_status,'changed',true,'payment_mode','disabled');
END
$$;
REVOKE ALL ON FUNCTION public.pd_native_pilot_trip_action(text,text,text,bigint) FROM PUBLIC;
COMMIT;
