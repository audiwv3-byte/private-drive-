# PRIVATE DRIVE pilot launch: isolated authorization regression

Trigger: GitHub Actions Validate release on this temporary branch.

Scope: signed Telegram authorization, passenger/admin/pilot role isolation, private orders, idempotency, payment status guards, lifecycle, frontend handlers.

Safety: all test data is local to the ephemeral CI runner. Do not call production booking or payment APIs. No production files or credentials modified.
