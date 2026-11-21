"""PRIVATE DRIVE planned weekly pilot identity-verification policy.

Pure offline decision logic: no camera/mic calls, biometric matching, uploads,
accounts, automatic account blocks or real-order operations.
"""
from datetime import datetime, timedelta, timezone

REVERIFY_AFTER = timedelta(days=7)


def identity_check_due(last_verified_at, *, now=None):
    """Fail closed: return True when never verified, invalid, future, or >=7d old."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if last_verified_at is None:
        return True
    if not isinstance(last_verified_at, datetime) or last_verified_at.tzinfo is None:
        return True
    elapsed = now.astimezone(timezone.utc) - last_verified_at.astimezone(timezone.utc)
    return elapsed < timedelta(0) or elapsed >= REVERIFY_AFTER


def proposed_driver_status(last_verified_at, *, now=None):
    """Display status only; caller must NOT treat this as production authorization."""
    return "verification_required" if identity_check_due(
        last_verified_at, now=now) else "verified"
