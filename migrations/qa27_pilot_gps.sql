BEGIN;
DO $guard$
BEGIN
 IF current_database() <> 'private_drive_test' THEN RAISE EXCEPTION 'QA27 test database required'; END IF;
END
$guard$;
CREATE TABLE IF NOT EXISTS public.pd_qa27_gps (
 order_id uuid PRIMARY KEY REFERENCES public.pd_dispatch_orders(id),
 pilot_id text NOT NULL REFERENCES public.native_auth_users(id),
 captured_at bigint NOT NULL,
 latitude double precision,
 longitude double precision,
 CHECK ((latitude IS NULL AND longitude IS NULL) OR
        (latitude IS NOT NULL AND longitude IS NOT NULL AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180))
);
REVOKE ALL ON public.pd_qa27_gps FROM PUBLIC;
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
 IF trip_status NOT IN ('assigned','approaching','underway') THEN RETURN jsonb_build_object('error','inactive_order'); END IF;
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
 WHERE g.order_id=oid AND o.status IN ('assigned','approaching','underway')
 AND g.latitude IS NOT NULL AND g.captured_at BETWEEN observed-30 AND observed+5
 AND public.pd_pilot_assignment_is_eligible(g.pilot_id,observed)),
 jsonb_build_object('available',false)) END
$gps$;
CREATE OR REPLACE FUNCTION public.pd_qa27_clear_finished_gps()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $gps$
BEGIN
 IF NEW.status IN ('finished','cancelled') THEN DELETE FROM public.pd_qa27_gps WHERE order_id=NEW.id; END IF;
 RETURN NEW;
END
$gps$;
DROP TRIGGER IF EXISTS pd_qa27_clear_finished_gps ON public.pd_dispatch_orders;
CREATE TRIGGER pd_qa27_clear_finished_gps AFTER UPDATE OF status ON public.pd_dispatch_orders
 FOR EACH ROW EXECUTE FUNCTION public.pd_qa27_clear_finished_gps();
REVOKE ALL ON FUNCTION public.pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_qa27_dispatch_gps(uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_qa27_clear_finished_gps() FROM PUBLIC;
COMMIT;
