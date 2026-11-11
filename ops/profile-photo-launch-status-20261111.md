# Profile photo UI — 2026-11-11

Installed only pd_live_home.js in /home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18.

Production module was read before editing. Existing two-stage registration, HEIC support and profile avatar endpoint are preserved. Added role photo editor access for administrator and pilot map home, visible native file picker, local preview and prompt to save.

Backup verified: /home/wilsonpark/private_drive_backups/snapshot_20261111T085522Z_8ceec6. Rollback: restore pd_live_home.js from this backup. No backend restart required: asset route reads JS from disk and sends no-cache.

Validation: node --check passed. Installer verified previous and replacement hashes and used atomic replacement. Public asset returned HTTP 200 with SHA-256 a2569579b3cff913b8074038f3e8cde65a652dda102d4c2246e9008414f65314. iPhone selection/upload and authenticated role UI still require verification inside Telegram. No real orders or payments created.

Prior PR #12 was based on older repository files; closed without merging or deploying.

Launch remains unconfirmed: verify user-facing photo replacement, order ownership, trip status controls/GPS, persisted pickup time, payment readiness and invoices against actual production, not repository-only tests.
