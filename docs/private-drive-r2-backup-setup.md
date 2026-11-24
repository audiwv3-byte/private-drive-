# PRIVATE DRIVE: encrypted test PostgreSQL backup (NOT ACTIVATED)

**Status:** draft only. No backups, deployments, billing changes, or secret uploads performed by this change.

## Strict boundaries

- Database allowed: `private_drive_test` only.
- R2 bucket: `private-drive-backups`, EU jurisdiction.
- GitHub Environment: `private-drive-backup`.
- Authorized branch: `backup/private-drive-r2`.
- Workflow: `.github/workflows/private-drive-r2-backup.yml`, manually dispatched only.
- No plaintext dump should be persisted or sent to GitHub Actions artifacts.

## Required Environment secrets (enter directly in GitHub, never in a PR)

| Name | Value source |
| --- | --- |
| `PG_TEST_DATABASE_URL` | **External** TLS connection URL for the Render TEST database only. Never production. |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 account API token, bucket-limited to `private-drive-backups`. |
| `R2_SECRET_ACCESS_KEY` | Matching R2 secret, stored only in GitHub Environment secrets. |

## Required Environment variables (non-secret)

| Name | Value source |
| --- | --- |
| `R2_ACCOUNT_ID` | Cloudflare 32-character account ID, **not** a token. |
| `AGE_RECIPIENT` | age **public** recipient, beginning `age1`. |

Do not commit a private age identity key to GitHub. Create and back up the private identity outside GitHub, test that it can decrypt a harmless sample, then keep a second encrypted/offline recovery copy. **The current iSH screenshot showed `age-keygen: not found` and no key file, so no age key has been verified.**

## Safety requirements to verify before activation

1. Verify Render Free PostgreSQL accepts outbound connection from GitHub-hosted runners with the external test-only URL and mandatory TLS.
2. Review workflow for correctness, including Docker image provenance, age installation, AWS CLI availability, R2 EU endpoint, strict database name checks, encryption and deletion policy.
3. Verify the GitHub Environment has exactly the protected branch and human review configured; verify its actual permission semantics on this public repository.
4. Existing ruleset `private-drive-backup-protection` requires **one approving PR review** with no bypass actor. With only one account, the PR may be unmergeable. Do not loosen these controls without separate authorization.
5. GitHub `workflow_dispatch` generally requires the workflow file on the default branch to appear as a manually triggerable workflow. This PR targets a nondefault protected branch and therefore **is intentionally not operational**. Do not add to `main` without separate authorization.
6. R2 token TTL is 30 days, requiring rotation. Confirm account and bucket free-tier charges before activation.
7. Perform an encrypted backup to R2 and an isolated restore test only under a **separate explicit authorization**. Do not use production.

## Operational status

The branch protection ruleset is verified by GitHub API as **active**, scoped to `refs/heads/backup/private-drive-r2`, requiring 1 approval, deletion protection and non-fast-forward protection. The backup workflow PR is open as draft, not merged.
