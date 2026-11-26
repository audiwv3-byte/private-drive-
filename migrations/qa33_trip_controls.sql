BEGIN;
DO $$ BEGIN IF current_database() <> 'private_drive_test' THEN RAISE EXCEPTION 'QA33 isolated database required'; END IF; END $$;
ALTER TABLE public.pd_dispatch_orders ADD COLUMN IF NOT EXISTS waiting_started_at bigint CHECK(waiting_started_at>=0);
ALTER TABLE public.pd_dispatch_orders ADD COLUMN IF NOT EXISTS waiting_seconds bigint NOT NULL DEFAULT 0 CHECK(waiting_seconds>=0);
ALTER TABLE public.pd_dispatch_orders DROP CONSTRAINT IF EXISTS pd_dispatch_orders_status_check;
ALTER TABLE public.pd_dispatch_orders ADD CONSTRAINT pd_dispatch_orders_status_check CHECK(status IN ('requested','assigned','approaching','arrived','underway','finished','cancelled'));
ALTER TABLE public.pd_dispatch_orders ADD COLUMN IF NOT EXISTS arrived_at bigint;
ALTER TABLE public.pd_dispatch_orders ADD COLUMN IF NOT EXISTS stop_charge_cents bigint NOT NULL DEFAULT 0 CHECK(stop_charge_cents>=0);
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
               o.trip_time, o.status, o.waiting_seconds + CASE WHEN o.waiting_started_at IS NULL THEN 0 ELSE greatest(0,observed_at-o.waiting_started_at) END AS waiting_seconds, (o.waiting_started_at IS NOT NULL) AS waiting_active, o.stop_charge_cents + CASE WHEN o.waiting_started_at IS NULL THEN 0 ELSE ((greatest(0,observed_at-o.waiting_started_at)+59)/60)*25 END AS stop_charge_cents
        FROM public.pd_native_order_assignments a
        JOIN public.pd_dispatch_orders o ON o.id = a.order_id
        WHERE a.pilot_user_id = principal.user_id
          AND o.status IN ('assigned','approaching','arrived','underway')
        ORDER BY a.assigned_at DESC, o.id
        LIMIT 100
    ) rows;
    RETURN jsonb_build_object('orders', result, 'payment_mode', 'disabled');
END
$$;


CREATE OR REPLACE FUNCTION public.pd_native_pilot_trip_action(
    supplied_digest text, target_order text, action text, observed_at bigint
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    principal record;
    current_status text;
    expected_status text;
    next_status text;
    wait_start bigint;
    wait_total bigint;
BEGIN
    SELECT * INTO principal FROM public.pd_validate_native_session(supplied_digest, observed_at);
    IF NOT FOUND THEN RETURN jsonb_build_object('error','invalid_session'); END IF;
    IF principal.server_role NOT IN ('pilot','pilot_dispatcher')
       OR NOT public.pd_pilot_assignment_is_eligible(principal.user_id, observed_at) THEN
        RETURN jsonb_build_object('error','pilot_required');
    END IF;
    CASE action
      WHEN 'approach' THEN expected_status := 'assigned'; next_status := 'approaching';
      WHEN 'arrive' THEN expected_status := 'approaching'; next_status := 'arrived';
      WHEN 'start' THEN expected_status := 'arrived'; next_status := 'underway';
      WHEN 'finish' THEN expected_status := 'underway'; next_status := 'finished';
      WHEN 'stop_start' THEN expected_status := 'underway'; next_status := 'underway';
      WHEN 'stop_end' THEN expected_status := 'underway'; next_status := 'underway';
      ELSE RETURN jsonb_build_object('error','invalid_action');
    END CASE;
    SELECT o.status,o.waiting_started_at,o.waiting_seconds INTO current_status,wait_start,wait_total FROM public.pd_dispatch_orders o
    JOIN public.pd_native_order_assignments a ON a.order_id=o.id
    WHERE o.id=target_order::uuid AND a.pilot_user_id=principal.user_id
    FOR UPDATE OF o;
    IF NOT FOUND THEN RETURN jsonb_build_object('error','order_not_found'); END IF;
    IF action IN ('stop_start','stop_end') THEN
        IF current_status <> 'underway' THEN RETURN jsonb_build_object('error','invalid_transition'); END IF;
        IF action='stop_start' AND wait_start IS NULL THEN
            UPDATE public.pd_dispatch_orders SET waiting_started_at=observed_at WHERE id=target_order::uuid;
            RETURN jsonb_build_object('order_id',target_order,'status',current_status,'changed',true,'waiting_active',true,'waiting_seconds',wait_total,'payment_mode','disabled');
        ELSIF action='stop_end' AND wait_start IS NOT NULL THEN
            wait_total := wait_total + greatest(0,observed_at-wait_start);
            UPDATE public.pd_dispatch_orders SET waiting_started_at=NULL,waiting_seconds=wait_total,stop_charge_cents=stop_charge_cents+((greatest(0,observed_at-wait_start)+59)/60)*25 WHERE id=target_order::uuid;
            RETURN jsonb_build_object('order_id',target_order,'status',current_status,'changed',true,'waiting_active',false,'waiting_seconds',wait_total,'payment_mode','disabled');
        END IF;
        RETURN jsonb_build_object('order_id',target_order,'status',current_status,'changed',false,'waiting_active',wait_start IS NOT NULL,'waiting_seconds',wait_total,'payment_mode','disabled');
    END IF;
    IF action='finish' AND wait_start IS NOT NULL THEN RETURN jsonb_build_object('error','invalid_transition'); END IF;
    IF current_status=next_status THEN
        RETURN jsonb_build_object('order_id',target_order,'status',current_status,'changed',false,'payment_mode','disabled');
    END IF;
    IF current_status<>expected_status THEN RETURN jsonb_build_object('error','invalid_transition'); END IF;
    UPDATE public.pd_dispatch_orders SET status=next_status, arrived_at=CASE WHEN action='arrive' THEN observed_at ELSE arrived_at END WHERE id=target_order::uuid;
    RETURN jsonb_build_object('order_id',target_order,'status',next_status,'changed',true,'payment_mode','disabled');
END
$$;
REVOKE ALL ON FUNCTION public.pd_native_pilot_trip_action(text,text,text,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.pd_qa27_write_gps(digest text, oid uuid, enabled boolean,
 lat double precision, lon double precision, captured bigint, observed bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $gps$
DECLARE p record; trip_status text; prior bigint;
BEGIN
 SELECT * INTO p FROM public.pd_validate_native_session(digest,observed);
 IF NOT FOUND THEN RETURN jsonb_build_object('error','invalid_session'); END IF;
 IF p.server_role NOT IN ('pilot','pilot_dispatcher') OR NOT public.pd_pilot_assignment_is_eligible(p.user_id,observed)
 THEN RETURN jsonb_build_object('error','pilot_required'); END IF;
 SELECT o.status INTO trip_status FROM public.pd_dispatch_orders o
 JOIN public.pd_native_order_assignments a ON a.order_id=o.id
 WHERE o.id=oid AND a.pilot_user_id=p.user_id FOR UPDATE OF o;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','order_not_found'); END IF;
 IF trip_status NOT IN ('assigned','approaching','arrived','underway') THEN RETURN jsonb_build_object('error','inactive_order'); END IF;
 IF enabled IS NULL OR captured IS NULL OR captured<observed-30 OR captured>observed+5
 OR (enabled AND (lat IS NULL OR lon IS NULL OR NOT(lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180)))
 OR (NOT enabled AND (lat IS NOT NULL OR lon IS NOT NULL)) THEN
 RETURN jsonb_build_object('error','invalid_fix'); END IF;
 SELECT g.captured_at INTO prior FROM public.pd_qa27_gps g WHERE g.order_id=oid;
 -- A stop wins over a fix with the same timestamp. Replaying that stop is safe.
 IF prior IS NOT NULL AND (captured<prior OR (captured=prior AND enabled))
 THEN RETURN jsonb_build_object('error','stale_fix'); END IF;
 INSERT INTO public.pd_qa27_gps(order_id,pilot_id,captured_at,latitude,longitude)
 VALUES(oid,p.user_id,captured,lat,lon)
 ON CONFLICT(order_id) DO UPDATE SET pilot_id=excluded.pilot_id,captured_at=excluded.captured_at,
 latitude=excluded.latitude,longitude=excluded.longitude;
 RETURN jsonb_build_object('available',enabled);
END
$gps$;
CREATE OR REPLACE FUNCTION public.pd_qa27_dispatch_gps(oid uuid, observed bigint)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $gps$
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM public.pd_dispatch_orders WHERE id=oid)
 THEN jsonb_build_object('error','order_not_found')
 ELSE COALESCE((SELECT jsonb_build_object('available',true,'latitude',g.latitude,'longitude',g.longitude,'captured_at',g.captured_at)
 FROM public.pd_qa27_gps g JOIN public.pd_dispatch_orders o ON o.id=g.order_id
 JOIN public.pd_native_order_assignments a ON a.order_id=o.id AND a.pilot_user_id=g.pilot_id
 WHERE g.order_id=oid AND o.status IN ('assigned','approaching','arrived','underway')
 AND g.latitude IS NOT NULL AND g.captured_at BETWEEN observed-30 AND observed+5
 AND public.pd_pilot_assignment_is_eligible(g.pilot_id,observed)),
 jsonb_build_object('available',false)) END
$gps$;

COMMIT;
