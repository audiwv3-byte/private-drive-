# PRIVATE DRIVE — isolated test-only cross-device sync

Scope: \`feature/flutter-independent-auth\`. Nothing here deploys to PythonAnywhere,
Telegram Mini App or production. There is **no payment gateway, real driver
assignment, production user database or real booking API**.

## Design and isolation

- Python 3 standard-library HTTP API, bound to \`127.0.0.1\` ONLY.
- One synthetic test identity per role: \`passenger_test\`, \`pilot_test\`,
  \`dispatcher_test\`. Separate long-lived **temporary** bearer secrets are
  supplied by the test operator at runtime, not committed to Git.
- API checks the **server-derived** role for every request; selecting a
  frontend screen does not grant permissions. The pilot sees only trips
  assigned to its synthetic identity.
- SQLite survives server restart; transactions and an optimistic \`version\`
  reject stale/disallowed transitions. Append-only event log supports
  \`GET /v1/trips/{id}/events?after=N\`. No real SMS/PayPal/Stripe.
- Native Flutter client manually accepts a **separate HTTPS URL** and its
  corresponding role token. Tokens are held only in memory, and need to be
  entered again after restart. The trip itself is restored from the test
  SQLite service on reconnection; the client polls for updates every 3 sec.
- The backend deliberately denies browser-origin requests; there is no CORS
  and no browser admin panel. Requests never expose bearer tokens in logs.
- The pilot's remote screen remains map-first. GPS is explicit opt-in and
  remains on-device; location coordinates are **not** sent to this test API.

## Run safely on a throwaway development machine

Generate three independent random test secrets using Python's
\`secrets.token_urlsafe(32)\`. Set the following **locally** (not GitHub
Secrets for this offline CI, and never production keys):

\`\`\`sh
export PD_DEMO_ISOLATED=YES
export PD_DEMO_PASSENGER_TOKEN='<random independent token, at least 32 chars>'
export PD_DEMO_PILOT_TOKEN='<random independent token, at least 32 chars>'
export PD_DEMO_DISPATCHER_TOKEN='<random independent token, at least 32 chars>'
export PD_DEMO_DB='/tmp/private-drive-isolated-demo.sqlite'
python3 test_sync_server/pd_demo_server.py
\`\`\`

The server listens at \`127.0.0.1:8765\` by default. This address is not
reachable from separate physical phones. **Do not expose port 8765 to the
Internet or bind the server to 0.0.0.0.** To test across real devices, a
separate temporary TLS-terminating reverse proxy on a trusted development
network is required. Configure a trusted HTTPS certificate, isolate the
network, enforce rate limits and delete test credentials/database afterward.
The proxy is **not** created or deployed by this repository. No third-party
hosting/tunnel or paid service is used by CI.

Open the application's **test interface** → **Тестовая связь между
устройствами**. On each phone use the same isolated HTTPS proxy URL and the
distinct passenger, pilot or dispatcher token. Verify the sequence:
passenger creates a dummy trip → dispatcher assigns \`pilot_test\` → pilot
advances/pauses/resumes/finishes → passenger sees updated statuses. Reconnect
after restarting the client to verify server-side recovery.

## Offline API smoke-test

\`\`\`sh
PYTHONPATH=test_sync_server python3 -m unittest discover \
  -s test_sync_server -p 'test_*.py' -v
\`\`\`

Endpoints (all require bearer auth):

| Method | Endpoint | Allowed role |
| --- | --- | --- |
| GET | \`/v1/me\` | all |
| GET | \`/v1/current\` | all; only visible trip |
| POST | \`/v1/trips\` | passenger |
| GET | \`/v1/trips/{id}\` | owner, assigned pilot, dispatcher |
| GET | \`/v1/trips/{id}/events?after=N\` | same as above |
| POST | \`/v1/trips/{id}/assign\` | dispatcher |
| POST | \`/v1/trips/{id}/action\` | assigned pilot |

Statuses: \`requested → assigned → approaching → underway → finished\`.
\`pause\` and \`resume\` keep the current stage. Every mutation requires the
latest integer \`version\`; \`409 version_conflict\` means refresh first.

**Not a production-ready dispatch service.** It has single-purpose static
test principals, no account provisioning, durable client credentials or
device push, and no tested remote deployment, load balancing or abuse
protection. Never substitute its bearer tokens or test SQLite for actual
authenticated customer accounts. Location and OSM tile usage must also be
validated under real mobile conditions separately.
