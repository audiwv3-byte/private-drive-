"""Offline encrypted pg_dump for PRIVATE DRIVE's expiring staging PostgreSQL.

Never executed automatically. No plaintext dump, no secret in command arguments.
Run ONLY on a trusted persistent machine with an age recipient public key.
The encrypted archive must stay outside GitHub, CI artifacts and Render ephemeral
storage. Backups include personal data: decryption key stays offline.
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

EXPECTED_DB = "private_drive_test"


def source_env(raw_url):
    if not isinstance(raw_url, str) or not raw_url:
        raise ValueError("missing_source")
    parts = urlsplit(raw_url)
    if parts.scheme not in ("postgres", "postgresql") or (parts.path or "") != "/" + EXPECTED_DB:
        raise ValueError("incorrect_staging_database")
    if not parts.hostname or not parts.username or parts.password is None:
        raise ValueError("incomplete_source")
    if parts.query or parts.fragment:
        raise ValueError("unsupported_connection_options")
    env = dict(os.environ)
    env.update(PGHOST=parts.hostname, PGPORT=str(parts.port or 5432),
               PGDATABASE=EXPECTED_DB, PGUSER=unquote(parts.username),
               PGPASSWORD=unquote(parts.password), PGSSLMODE="require")
    return env


def validate_environment():
    if os.environ.get("PD_DISPATCH_STAGING_ONLY") != "1":
        raise ValueError("not_isolated_staging")
    if os.environ.get("PD_BACKUP_EXPLICIT_APPROVAL") != "YES":
        raise ValueError("not_explicitly_authorized")
    if os.environ.get("PD_DISPATCH_REGISTRY_ENABLED") == "1":
        raise ValueError("registry_migration_already_enabled")
    recipient = os.environ.get("PD_BACKUP_AGE_RECIPIENT", "")
    if not re.fullmatch(r"age1[0-9a-z]{58}", recipient):
        raise ValueError("invalid_age_public_recipient")
    dest = Path(os.environ.get("PD_BACKUP_DESTINATION", ""))
    if not dest.is_absolute() or dest.suffix != ".age":
        raise ValueError("invalid_destination")
    if not dest.parent.is_dir():
        raise ValueError("destination_directory_missing")
    return recipient, dest, source_env(os.environ.get("PD_BACKUP_SOURCE_URL"))


def encrypted_export():
    recipient, dest, env = validate_environment()
    # Exclusive create prevents overwriting existing backups. No plaintext file.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(dest), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            pg = subprocess.Popen(["pg_dump", "--format=custom", "--no-owner",
                    "--no-acl", "--schema=public"], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=env)
            age = subprocess.Popen(["age", "--encrypt", "--recipient", recipient],
                                   stdin=pg.stdout, stdout=output,
                                   stderr=subprocess.DEVNULL)
            pg.stdout.close()
            encryption_exit = age.wait()
            dump_exit = pg.wait()
            if dump_exit or encryption_exit or dest.stat().st_size < 128:
                raise RuntimeError("encrypted_export_failed")
        # Verify the public age v1 header, never inspect decrypted contents.
        with dest.open("rb") as sealed:
            if sealed.readline(64) != b"age-encryption.org/v1\n":
                raise RuntimeError("not_an_age_archive")
        os.chmod(dest, 0o600)
        return "ENCRYPTED_BACKUP_CREATED"
    except BaseException:
        try: dest.unlink(missing_ok=True)
        except OSError: pass
        raise


if __name__ == "__main__":
    try:
        print(encrypted_export())
    except Exception:
        # Don't print exception details: they may contain URLs or credentials.
        print("BACKUP_FAILED_CHECK_LOCAL_CONFIGURATION", file=sys.stderr)
        sys.exit(1)
