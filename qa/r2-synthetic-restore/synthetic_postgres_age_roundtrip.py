#!/usr/bin/env python3
"""Offline integration rehearsal; freshly created private PostgreSQL UNIX socket only."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from synthetic_archive_policy import EXCLUDE_DATA, reviewed_dump_flags

TOOLS = ("initdb", "pg_ctl", "psql", "pg_dump", "pg_restore", "age", "age-keygen")
SOURCE = "pd_schema_ci"
TARGET = "pd_schema_restored"
PORT = "55479"
OPERATOR = "pd_synthetic_operator"
OWNER = "pd_synthetic_owner"
BASE = Path(__file__).resolve().parent

SEED = """
CREATE TABLE public.native_auth_users(id text PRIMARY KEY);
CREATE TABLE public.native_auth_roles(
  user_id text PRIMARY KEY REFERENCES public.native_auth_users(id), role text NOT NULL);
CREATE TABLE public.native_auth_sessions (
  token_hash text PRIMARY KEY, user_id text NOT NULL REFERENCES public.native_auth_users(id),
  created_at bigint NOT NULL, expires_at bigint NOT NULL, revoked_at bigint);
CREATE TABLE public.native_identity_checks (
  id text PRIMARY KEY, user_id text REFERENCES public.native_auth_users(id),
  status text NOT NULL, photo bytea, expires_at bigint);
CREATE TABLE public.native_twilio_challenges(id text PRIMARY KEY, phone text);
CREATE TABLE public.pd_native_closed_pilot_invites(invite_hash text PRIMARY KEY);
CREATE TABLE public.pd_qa_pilot_applications(id text PRIMARY KEY, name text);
CREATE TABLE public.pd_qa_pilot_documents (
  id text REFERENCES public.pd_qa_pilot_applications(id), encrypted_bytes bytea);
CREATE TABLE public.pd_site_funnel(id text PRIMARY KEY, visit text);
CREATE TABLE public.pd_pilot_reviews (
  user_id text PRIMARY KEY REFERENCES public.native_auth_users(id), review_status text NOT NULL);
CREATE TABLE public.pd_dispatch_orders (id text PRIMARY KEY, status text NOT NULL);
CREATE TABLE public.pd_native_order_owners(
  order_id text PRIMARY KEY REFERENCES public.pd_dispatch_orders(id),
  user_id text NOT NULL REFERENCES public.native_auth_users(id));

INSERT INTO public.native_auth_users VALUES ('synthetic-user'), ('synthetic-pilot');
INSERT INTO public.native_auth_roles VALUES
  ('synthetic-user', 'passenger'), ('synthetic-pilot', 'pilot');
INSERT INTO public.native_auth_sessions VALUES
  (repeat('a',64), 'synthetic-user', 10, 1000, NULL);
INSERT INTO public.native_identity_checks VALUES
  ('synthetic-check', 'synthetic-pilot', 'pending', decode('000102ff','hex'), 1000);
INSERT INTO public.native_twilio_challenges VALUES ('synthetic-challenge','synthetic-phone');
INSERT INTO public.pd_native_closed_pilot_invites VALUES (repeat('b',64));
INSERT INTO public.pd_qa_pilot_applications VALUES ('synthetic-app','synthetic-pilot');
INSERT INTO public.pd_qa_pilot_documents VALUES ('synthetic-app',decode('f1f2f3','hex'));
INSERT INTO public.pd_site_funnel VALUES ('synthetic-event','synthetic-visit');
INSERT INTO public.pd_pilot_reviews VALUES ('synthetic-pilot','approved');
INSERT INTO public.pd_dispatch_orders VALUES ('synthetic-order','requested');
INSERT INTO public.pd_native_order_owners VALUES ('synthetic-order','synthetic-user');
"""
DURABLE = (
    "native_auth_users", "native_auth_roles", "pd_pilot_reviews",
    "pd_dispatch_orders", "pd_native_order_owners",
)
ACL = """
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO pd_synthetic_api, pd_synthetic_dispatch;
GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint),
    public.pd_revoke_current_session(text,bigint) TO pd_synthetic_api;
GRANT SELECT (id,user_id,status,photo,expires_at),
    INSERT (id,user_id,status,photo,expires_at), UPDATE (status,photo)
    ON public.native_identity_checks TO pd_synthetic_api;
GRANT SELECT ON public.pd_dispatch_orders TO pd_synthetic_dispatch;
COMMIT;
"""


class Blocked(Exception):
    pass


class Rehearsal:
    def __init__(self, work):
        self.work = work
        self.socket = work / "sock"
        self.data = work / "db"
        self.socket.mkdir(mode=0o700)
        self.env = {
            "PATH": os.environ["PATH"], "LANG": "C", "HOME": str(work),
            "PGCONNECT_TIMEOUT": "4",
        }
        self.bins = {tool: shutil.which(tool, path=self.env["PATH"]) for tool in TOOLS}
        missing = [name for name, path in self.bins.items() if not path]
        if missing:
            raise Blocked("MISSING_OFFLINE_TOOLS " + ",".join(missing))

    def command(self, tool, *args, payload=None):
        # No inherited PGHOSTADDR/PGSERVICE/PG* overrides.
        result = subprocess.run(
            [self.bins[tool], *map(str, args)],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.env, timeout=45, check=False,
        )
        if result.returncode:
            raise Blocked("LOCAL_COMMAND_FAILED " + tool)
        return result.stdout

    def pgargs(self, database):
        if database not in ("postgres", SOURCE, TARGET):
            raise Blocked("NON_SYNTHETIC_DATABASE_REFUSED")
        return ("-h", str(self.socket), "-p", PORT, "-U", OPERATOR, "-d", database)

    def sql(self, database, sql):
        return self.command("psql", "-XqAt", "-v", "ON_ERROR_STOP=1",
                            *self.pgargs(database), payload=sql.encode()).decode().strip()

    def relation_names(self):
        return self.sql(SOURCE, """
            SELECT c.relname
              FROM pg_catalog.pg_class c
              JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname='public' AND c.relkind IN ('r','p','m','f')
             ORDER BY c.relname;
        """).splitlines()

    def pipe(self, leader, follower, output=subprocess.PIPE):
        first = subprocess.Popen(
            [self.bins[leader[0]], *leader[1:]], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=self.env,
        )
        try:
            with subprocess.Popen(
                [self.bins[follower[0]], *follower[1:]], stdin=first.stdout,
                stdout=output, stderr=subprocess.DEVNULL, env=self.env,
            ) as second:
                try:
                    # pg_restore --list can complete before it consumes stdin.
                    # A private drainer consumes any trailing bytes without writing them.
                    def discard_trailing_bytes():
                        while first.stdout.read(65536):
                            pass

                    drain = threading.Thread(target=discard_trailing_bytes, daemon=True)
                    result, _ = second.communicate(timeout=45)
                    drain.start()
                    first.wait(timeout=45)
                    drain.join(timeout=1)
                except BaseException:
                    second.kill()
                    first.kill()
                    raise
                if first.returncode or second.returncode:
                    raise Blocked("LOCAL_PIPE_FAILED " + leader[0] + "+" + follower[0])
                return result
        finally:
            if first.poll() is None:
                first.kill()
            first.wait()
            first.stdout.close()

    def start(self):
        version = self.command("pg_dump", "--version").decode()
        if not re.search(r"\) (?:18|19|[2-9][0-9])(?:\.|\s)", version):
            raise Blocked("PG_DUMP_18_OR_LATER_REQUIRED")
        self.command("initdb", "-D", self.data, "-U", OPERATOR,
                     "--auth-local=trust", "--auth-host=reject", "--no-locale",
                     "--encoding=UTF8")
        # Fresh cluster with no TCP listener and a UID-only socket directory.
        self.command("pg_ctl", "-D", self.data, "-l", self.work / "server.log", "-w",
                     "-o", "-h '' -k " + str(self.socket) + " -p " + PORT, "start")
        if self.sql("postgres", "SHOW listen_addresses;") != "":
            raise Blocked("NETWORK_LISTENER_REFUSED")
        self.sql("postgres", "CREATE DATABASE " + SOURCE + " TEMPLATE template0;")

    def archive(self, name, recipient):
        flags = reviewed_dump_flags(self.relation_names())  # Fails before opening any file.
        dest = self.work / name
        if dest.suffix != ".age" or dest.parent != self.work:
            raise Blocked("INVALID_SYNTHETIC_ARCHIVE_NAME")
        # Exclusive creation; only remove output created by this call.
        with dest.open("xb") as sealed:
            try:
                self.pipe(
                    ("pg_dump", *self.pgargs(SOURCE), "--format=custom", "--no-owner",
                     "--no-acl", "--no-large-objects", "--schema=public", *flags),
                    ("age", "--encrypt", "--recipient", recipient), output=sealed,
                )
            except BaseException:
                dest.unlink()
                raise
        with dest.open("rb") as sealed:
            if sealed.readline(64) != b"age-encryption.org/v1\n":
                dest.unlink()
                raise Blocked("NOT_AGE_ARCHIVE")
        return dest

    def run(self):
        self.start()
        self.sql(SOURCE, SEED)
        self.sql(SOURCE, (BASE / "synthetic_native_auth_session_functions.sql").read_text())
        require(self.sql(SOURCE, """
          SELECT count(*) FROM public.pd_validate_native_session(repeat('a',64),20);
        """) == "1", "SOURCE_SESSION_SENTINEL_MISSING")
        for table in EXCLUDE_DATA:
            require(self.sql(SOURCE, f"SELECT count(*) FROM public.{table};") == "1",
                    "SOURCE_TRANSIENT_SENTINEL_MISSING")

        key = self.work / "identity"
        self.command("age-keygen", "-o", key)
        recipient = self.command("age-keygen", "-y", key).decode().strip()

        # Verify the unknown-schema case at the actual archive entry point.
        self.sql(SOURCE, "CREATE TABLE public.unreviewed_photo_archive(bytes bytea);")
        try:
            self.archive("must-not-exist.age", recipient)
        except ValueError as error:
            require(str(error) == "uncategorized_relation", "WRONG_DRIFT_REJECTION")
        else:
            raise Blocked("CATALOG_DRIFT_NOT_REJECTED")
        require(not (self.work / "must-not-exist.age").exists(), "UNSAFE_ARCHIVE_CREATED")
        self.sql(SOURCE, "DROP TABLE public.unreviewed_photo_archive;")

        dest = self.archive("synthetic.age", recipient)
        decoder = ("age", "--decrypt", "--identity", str(key), str(dest))
        toc = self.pipe(decoder, ("pg_restore", "--list")).decode()
        for table in EXCLUDE_DATA:
            escaped = re.escape(table)
            require(re.search(r"\bTABLE public " + escaped + r"\b", toc) is not None,
                    "EXCLUDED_TABLE_DEFINITION_MISSING")
            require(re.search(r"\bTABLE DATA public " + escaped + r"\b", toc) is None,
                    "TRANSIENT_ROWS_IN_ARCHIVE")
        for table in DURABLE:
            require(re.search(r"\bTABLE DATA public " + re.escape(table) + r"\b", toc) is not None,
                    "DURABLE_TABLE_DATA_MISSING")

        self.sql("postgres", f"""
            CREATE ROLE {OWNER} NOLOGIN;
            CREATE ROLE pd_synthetic_api NOLOGIN;
            CREATE ROLE pd_synthetic_dispatch NOLOGIN;
            CREATE ROLE pd_synthetic_outsider NOLOGIN;
            CREATE DATABASE {TARGET} OWNER {OWNER} TEMPLATE template0;
            REVOKE CONNECT ON DATABASE {TARGET} FROM PUBLIC;
        """)
        self.sql(TARGET, "DROP SCHEMA public;")
        self.pipe(decoder, ("pg_restore", *self.pgargs(TARGET), "--role", OWNER,
                            "--no-owner", "--no-acl", "--single-transaction"))
        self.sql(TARGET, ACL)

        for table in EXCLUDE_DATA:
            require(self.sql(TARGET, f"SELECT count(*) FROM public.{table};") == "0",
                    "EXCLUDED_TABLE_NOT_EMPTY")
        for table in DURABLE:
            digest = f"""
              SELECT md5(string_agg(to_jsonb(r)::text, '|' ORDER BY to_jsonb(r)::text))
              FROM public.{table} AS r;
            """
            before, after = self.sql(SOURCE, digest), self.sql(TARGET, digest)
            require(bool(before) and before == after, "DURABLE_DATA_MISMATCH")
        acl_ok = self.sql(TARGET, """
          SELECT NOT has_database_privilege('pd_synthetic_outsider',current_database(),'CONNECT')
            AND NOT has_schema_privilege('pd_synthetic_api','public','CREATE')
            AND NOT has_schema_privilege('pd_synthetic_dispatch','public','CREATE')
            AND NOT has_schema_privilege('pd_synthetic_outsider','public','CREATE')
            AND NOT has_table_privilege('pd_synthetic_dispatch','public.native_identity_checks','SELECT')
            AND NOT has_any_column_privilege('pd_synthetic_dispatch','public.native_identity_checks','SELECT')
            AND NOT has_any_column_privilege('pd_synthetic_outsider','public.native_identity_checks','SELECT')
            AND has_column_privilege('pd_synthetic_api','public.native_identity_checks','photo','SELECT')
            AND NOT has_table_privilege('pd_synthetic_api','public.native_auth_sessions','SELECT')
            AND NOT has_table_privilege('pd_synthetic_api','public.native_identity_checks','DELETE')
            AND has_table_privilege('pd_synthetic_dispatch','public.pd_dispatch_orders','SELECT')
            AND NOT has_table_privilege('pd_synthetic_dispatch','public.pd_dispatch_orders','UPDATE')
            AND has_function_privilege('pd_synthetic_api',
                'public.pd_validate_native_session(text,bigint)','EXECUTE')
            AND NOT has_function_privilege('pd_synthetic_outsider',
                'public.pd_validate_native_session(text,bigint)','EXECUTE')
            AND NOT has_function_privilege('pd_synthetic_dispatch',
                'public.pd_revoke_current_session(text,bigint)','EXECUTE')
            AND (SELECT pg_catalog.pg_get_userbyid(proowner)='pd_synthetic_owner'
                 FROM pg_catalog.pg_proc
                 WHERE oid='public.pd_validate_native_session(text,bigint)'::regprocedure);
        """)
        require(acl_ok == "t", "RESTORED_ROLE_ACL_MISMATCH")
        require(self.sql(TARGET, """
            SET ROLE pd_synthetic_api;
            SELECT count(*) FROM public.pd_validate_native_session(repeat('a',64),20);
        """) == "0", "STALE_SESSION_AUTHENTICATES_AFTER_RESTORE")
        print("SYNTHETIC_AGE_ROUNDTRIP_AND_RESTORED_ACL_VERIFIED")

    def stop(self):
        if self.data.exists():
            try:
                self.command("pg_ctl", "-D", self.data, "-m", "immediate", "-w", "stop")
            except (Blocked, OSError, subprocess.TimeoutExpired):
                pass


def require(condition, error):
    if not condition:
        raise Blocked(error)


def main():
    if len(sys.argv) != 1:
        raise Blocked("ARGUMENTS_REFUSED_SYNTHETIC_LOCAL_ONLY")
    if os.geteuid() == 0:
        raise Blocked("ROOT_REFUSED_SYNTHETIC_LOCAL_ONLY")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="pd-r2-ci-", dir="/tmp") as directory:
        runner = Rehearsal(Path(directory))
        try:
            runner.run()
        finally:
            runner.stop()


if __name__ == "__main__":
    try:
        main()
    except Blocked as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("SYNTHETIC_ROUNDTRIP_ABORTED_NO_LOGGED_DATA", file=sys.stderr)
        sys.exit(1)
