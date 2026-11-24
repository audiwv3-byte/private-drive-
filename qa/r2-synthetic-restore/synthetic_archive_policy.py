"""Data filtering for the disposable encrypted archive rehearsal."""

EXCLUDE_DATA = frozenset({
    "native_auth_sessions",
    "native_twilio_challenges",
    "native_identity_checks",
    "pd_native_closed_pilot_invites",
    "pd_qa_pilot_applications",
    "pd_qa_pilot_documents",
    "pd_site_funnel",
})
PRESERVE_DATA = frozenset({
    "native_auth_users",
    "native_auth_roles",
    "pd_account_telegram_links",
    "pd_account_profiles",
    "pd_pilot_reviews",
    "pd_dispatch_orders",
    "pd_native_order_owners",
    "pd_native_order_assignments",
    # Explicit review before any actual archive: this ledger prevents reuse
    # of consumed codes and has to be kept, or those codes must be invalidated.
    "private_drive_dispatcher_recoveries",
})


def reviewed_dump_flags(relations):
    """Require an exact reviewed catalog; fail closed on any different relation."""
    observed = frozenset(relations)
    if not {"native_auth_users", "native_auth_roles"}.issubset(observed):
        raise ValueError("unexpected_staging_catalog")
    if observed - (EXCLUDE_DATA | PRESERVE_DATA):
        raise ValueError("uncategorized_relation")
    # PG18 option also excludes table descendants if one of these is partitioned.
    return tuple(
        f"--exclude-table-data-and-children=public.{name}"
        for name in sorted(observed & EXCLUDE_DATA)
    )
