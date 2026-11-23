"""Offline-only validation for staged PRIVATE DRIVE PostgreSQL credential split.

No PostgreSQL connections; no Render API calls; no environment mutation.
Do not wire these variables into live services until a reviewed migration
and verified backup exist. All diagnostics are keys/codes, never DSN values.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit

ROLE_VARIABLES = {
    "runtime": "PD_DB_RUNTIME_URL",
    "reviewer": "PD_DB_REVIEWER_URL",
    "migrator": "PD_DB_MIGRATOR_URL",
}
LEGACY_VARIABLES = ("PD_DISPATCH_DATABASE_URL", "PD_NATIVE_DATABASE_URL", "DATABASE_URL")
EXPECTED_DATABASE = "private_drive_test"


@dataclass(frozen=True)
class TransitionAudit:
    ready_for_next_review: bool
    codes: tuple[str, ...]
    legacy_configured: tuple[str, ...]
    candidate_roles: tuple[str, ...]


def _parse_url(value):
    """Validate only topology and role names; never return credentials."""
    if not isinstance(value, str) or not value:
        raise ValueError("missing_url")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise ValueError("unsafe_url")
    try:
        url = urlsplit(value)
        port = url.port or 5432
    except (ValueError, TypeError):
        raise ValueError("invalid_url") from None
    if (url.scheme not in ("postgres", "postgresql") or not url.hostname
            or not url.username or url.password is None or not 1 <= port <= 65535
            or url.path != "/" + EXPECTED_DATABASE or url.query or url.fragment):
        raise ValueError("invalid_url")
    return (url.hostname.lower(), port, url.path), url.username


def audit_transition(env):
    """Check whether isolated future URLs could be reviewed, not deployed.

    Current credentials are intentionally never accessed beyond presence.
    A candidate cannot be used as an active connection in this module.
    """
    found_legacy = tuple(name for name in LEGACY_VARIABLES if env.get(name))
    candidate_roles = tuple(role for role, name in ROLE_VARIABLES.items() if env.get(name))
    codes = []
    if env.get("PD_DISPATCH_STAGING_ONLY") != "1":
        codes.append("not_isolated_staging")
    if env.get("PD_NATIVE_SMS_LIVE") == "YES" or str(env.get("TWILIO_VERIFY_ENABLED", "")).lower() == "true":
        codes.append("real_sms_is_active")
    if not found_legacy:
        codes.append("legacy_binding_unconfirmed")
    if len(candidate_roles) != 3:
        codes.append("three_candidates_required")
    else:
        endpoints = []
        db_users = []
        for role, name in ROLE_VARIABLES.items():
            try:
                endpoint, db_user = _parse_url(env[name])
            except ValueError:
                codes.append(role + "_invalid")
            else:
                endpoints.append(endpoint)
                db_users.append(db_user)
        if len(endpoints) == 3:
            if len(set(endpoints)) != 1:
                codes.append("different_databases")
            if len(set(db_users)) != 3:
                codes.append("shared_database_login")
            if any(user in ("postgres", "private_drive_test_user", "pd_ci") for user in db_users):
                codes.append("privileged_or_ci_login")
    # These flags do not run a migration; refuse to claim readiness when enabled.
    if env.get("PD_DISPATCH_REGISTRY_ENABLED") == "1":
        codes.append("registry_already_enabled")
    return TransitionAudit(
        ready_for_next_review=not codes,
        codes=tuple(codes),
        legacy_configured=found_legacy,
        candidate_roles=candidate_roles,
    )


def compatibility_matrix():
    """Required database operations gathered from the existing codebase."""
    return {
        "native_phone_auth": (
            "legacy: app initialize_database creates tables/indexes",
            "request-code: insert challenge, select latest, advisory lock",
            "verify-code: update challenge, insert/select user, "
            "insert session, read role",
            "new runtime: scoped DML for users/challenges/sessions; no DDL",
        ),
        "dispatcher_auth": (
            "legacy: dispatcher password create/recover creates tables",
            "login: read password hash; recover: update hash, insert recovery",
            "new reviewer: scoped DML for dispatcher credentials and recovery; no DDL",
        ),
        "registry": (
            "existing: admin-only browser session read via dispatcher connector",
            "new runtime: masked projection, no token/document reads",
            "admin decisions: verified session and constrained approval function",
        ),
        "migrations": (
            "new migrator: explicit DDL and object ownership only",
            "no connection from public app or automatic web startup",
        ),
    }
