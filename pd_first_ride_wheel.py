"""One first-ride discount across the isolated passenger order channels."""
from secrets import randbelow
import os
import time

from pd_native_auth_postgres_session_lifecycle import _digest
from pd_qa_native_orders_mount import permitted

TTL = 7 * 86400
WINDOWS = ((45, 5), (80, 10), (95, 15), (100, 20))


def enabled():
    return os.getenv("PD_QA_FIRST_RIDE_WHEEL") == "1" and permitted(
        os.getenv("PD_DISPATCH_ORDERS_DATABASE_URL", ""))


def draw_percent(ticket):
    return next(percent for stop, percent in WINDOWS if ticket < stop)


def session_account(db, token, now):
    digest = _digest(token)
    if not digest:
        return None
    return db.execute("""
        SELECT u.id, u.destination FROM public.pd_validate_native_session(%s, %s) s
        JOIN public.native_auth_users u ON u.id=s.user_id
        WHERE u.channel='phone' AND u.destination ~ '^[+][1-9][0-9]{6,14}$'
    """, (digest, now)).fetchone()


def telegram_account(db, telegram_id):
    row = db.execute("""
        SELECT user_id FROM public.pd_account_telegram_links WHERE telegram_subject=%s
    """, (str(telegram_id),)).fetchone()
    return row[0] if row else None


def bind_telegram(db, telegram_id, user_id):
    # Both identities have been authenticated by this point. Existing bindings
    # remain immutable even if two linking attempts arrive concurrently.
    db.execute("""
        INSERT INTO public.pd_account_telegram_links
            (user_id, telegram_subject, verified_at, verification_method)
        VALUES (%s, %s, statement_timestamp(), 'mini_app_phone_session')
        ON CONFLICT DO NOTHING
    """, (user_id, str(telegram_id)))
    return telegram_account(db, telegram_id) == user_id


def _has_prior_order(db, user_id):
    return db.execute("""
        SELECT EXISTS (
            SELECT 1 FROM public.pd_native_order_owners WHERE user_id=%s
            UNION ALL
            SELECT 1 FROM public.pd_telegram_order_owners t
            JOIN public.pd_account_telegram_links l
                ON l.telegram_subject=t.telegram_id::text WHERE l.user_id=%s
        )
    """, (user_id, user_id)).fetchone()[0]


def _lock_account(db, user_id):
    db.execute("SELECT id FROM public.native_auth_users WHERE id=%s FOR UPDATE", (user_id,))


def reward(db, user_id, now, *, spin=False):
    if spin:
        _lock_account(db, user_id)
    row = db.execute("""
        SELECT percent, expires_at, order_id FROM public.pd_first_ride_rewards WHERE user_id=%s
    """, (user_id,)).fetchone()
    if row:
        percent, expires_at, order_id = row
        state = "used" if order_id else "available" if expires_at > now else "expired"
        return dict(state=state, percent=percent, expires_at=expires_at)
    if _has_prior_order(db, user_id):
        return dict(state="ineligible")
    if not spin:
        return dict(state="ready")
    percent = draw_percent(randbelow(100))
    db.execute("""
        INSERT INTO public.pd_first_ride_rewards (user_id, percent, expires_at) VALUES (%s, %s, %s)
    """, (user_id, percent, now + TTL))
    return dict(state="available", percent=percent, expires_at=now + TTL)


def prepare_order(db, user_id):
    _lock_account(db, user_id)
    return not _has_prior_order(db, user_id)


def redeem(db, user_id, order_id, *, eligible):
    if eligible:
        db.execute("""
            UPDATE public.pd_first_ride_rewards SET order_id=%s
            WHERE user_id=%s AND order_id IS NULL AND expires_at>%s
        """, (order_id, user_id, int(time.time())))
    return order_discount(db, order_id)


def order_discount(db, order_id):
    row = db.execute("""
        SELECT percent FROM public.pd_first_ride_rewards WHERE order_id=%s
    """, (order_id,)).fetchone()
    return row[0] if row else None


def discounted_cents(amount, percent):
    if amount is None or percent is None:
        return amount
    return amount - (amount * percent + 50) // 100
