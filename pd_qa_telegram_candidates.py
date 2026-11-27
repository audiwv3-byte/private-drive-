"""QA transport for Telegram applications. Documents stay with the Mini App."""
from contextlib import contextmanager
import os


class CandidateStoreUnavailable(RuntimeError):
    pass


def enabled():
    return (os.environ.get("PD_QA_MINIAPP_POSTGRES") == "1"
            and os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.environ.get("PD_PAYMENT_MODE") == "disabled"
            and os.environ.get("PD_NATIVE_SMS_LIVE") == "NO")


class CandidateStore:
    def __init__(self):
        self.dsn = os.environ.get("PD_QA_TELEGRAM_CANDIDATES_DATABASE_URL", "")

    @contextmanager
    def transaction(self):
        if not self.dsn.startswith(("postgresql://", "postgres://")):
            raise CandidateStoreUnavailable
        import psycopg
        from psycopg.rows import dict_row

        try:
            with psycopg.connect(self.dsn, connect_timeout=4, row_factory=dict_row,
                                 options="-c statement_timeout=4000") as db:
                yield db
        except psycopg.Error as exc:
            raise CandidateStoreUnavailable from exc

    @staticmethod
    def publish(db, application):
        db.execute("""
            INSERT INTO public.pd_qa_telegram_candidates
                (telegram_id, name, phone, city, vehicle, vehicle_year, plate, seats,
                 status, created_at, updated_at)
            VALUES (%(telegram_id)s, %(name)s, %(phone)s, %(city)s, %(vehicle)s,
                    %(vehicle_year)s, %(plate)s, %(seats)s, %(status)s, %(created_at)s, %(updated_at)s)
            ON CONFLICT (telegram_id) DO UPDATE SET
                name = EXCLUDED.name, phone = EXCLUDED.phone, city = EXCLUDED.city,
                vehicle = EXCLUDED.vehicle, vehicle_year = EXCLUDED.vehicle_year,
                plate = EXCLUDED.plate, seats = EXCLUDED.seats, status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
        """, dict(application))

    def recent(self):
        with self.transaction() as db:
            return db.execute("""
                SELECT name, phone, city, vehicle, vehicle_year, plate, status
                FROM public.pd_qa_telegram_candidates
                ORDER BY updated_at DESC, telegram_id DESC LIMIT 200
            """).fetchall()
