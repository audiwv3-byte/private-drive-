"""Restricted operator-only command; no HTTP issuer and no outbound delivery."""
import argparse
import json
import os
from pathlib import Path
import secrets

from pd_native_closed_invites import TEST_DB, _hash, pilot_enabled


def issue(database_url, output, hours, *, env, user_id=None):
    if not pilot_enabled(database_url, env) or not 1 <= hours <= 24:
        raise ValueError("closed_pilot_operator_guard_refused")
    import psycopg

    new_user = user_id is None
    user_id = secrets.token_urlsafe(24) if new_user else user_id
    code = secrets.token_urlsafe(32)
    # Create exclusively, before a DB write, and never print a code to stdout.
    # Keep this output in a private directory outside any repository.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as secret_file:
            json.dump({"user_id": user_id, "invite_code": code}, secret_file)
            secret_file.write("\n")
            secret_file.flush()
            os.fsync(secret_file.fileno())

        with psycopg.connect(database_url, connect_timeout=4,
                             options="-c statement_timeout=4000") as db:
            db_name, now = db.execute(
                "SELECT current_database(), floor(extract(epoch FROM statement_timestamp()))::bigint"
            ).fetchone()
            if db_name != TEST_DB:
                raise ValueError("closed_pilot_operator_guard_refused")
            if new_user:
                db.execute(
                    "INSERT INTO public.native_auth_users (id,channel,destination,created_at) "
                    "VALUES (%s,'invite',%s,%s)", (user_id, secrets.token_urlsafe(24), now),
                )
            else:
                # Reissue only a verified operator-selected, existing invite identity.
                # Lock it so two operators cannot leave two pending invitations.
                matched = db.execute(
                    "SELECT u.id FROM public.native_auth_users u "
                    "WHERE u.id=%s AND u.channel='invite' AND NOT EXISTS "
                    "(SELECT 1 FROM public.native_auth_roles r WHERE r.user_id=u.id AND r.role <> 'passenger') "
                    "FOR UPDATE", (user_id,),
                ).fetchone()
                if not matched:
                    raise ValueError("closed_pilot_operator_guard_refused")
                db.execute(
                    "UPDATE public.pd_native_closed_pilot_invites SET consumed_at=%s "
                    "WHERE user_id=%s AND consumed_at IS NULL", (now, user_id),
                )
            db.execute(
                "INSERT INTO public.pd_native_closed_pilot_invites "
                "(invite_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",
                (_hash(code), user_id, now, now + hours * 3600),
            )
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New private output file")
    parser.add_argument("--hours", type=int, default=6, choices=range(1, 25), metavar="1-24")
    parser.add_argument("--reissue-for-user", help="Existing invite user’s opaque internal ID")
    args = parser.parse_args()
    try:
        issue(os.environ.get("PD_CLOSED_PILOT_OPERATOR_DATABASE_URL", ""),
              args.output, args.hours, env=os.environ, user_id=args.reissue_for_user)
    except Exception:
        parser.exit(1, "Invite NOT reported as issued. Check isolated operator configuration and DB status.\n")


if __name__ == "__main__":
    main()
