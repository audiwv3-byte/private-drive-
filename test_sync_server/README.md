# PRIVATE DRIVE — isolated test-only cross-device sync

Scope: `feature/flutter-independent-auth`. Nothing here deploys to PythonAnywhere,
Telegram Mini App or production. There is **no payment gateway, real driver
assignment, production user database or real booking API**.

## Design and isolation

- Python 3 standard-library HTTP API, bound to `127.0.0.1` ONLY.
- One synthetic test identity per role: `passenger_test`, `pilot_test`,
  `dispatcher_test`. Separate long-lived **temporary** bearer secrets are
  supplied by the test operator at runtime, not committed to Git.
- API checks the **server-derived** role for every request; selecting a
  frontend screen does not grant permissions. The pilot sees only trips
  assigned to its synthetic identity.
- SQLite survives server restart; transactions and an optimistic `version`
  reject stale/disallowed transitions. Append-only event log supports
  `GET /v1/trips/{id}/events?after=N`. No real SMS/PayPal/Stripe.
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
`secrets.token_urlsafe(32)`. Set the following **locally** (not GitHub
Secrets for this offline CI, and never production keys):

```sh
export PD_DEMO_ISOLATED=YES
export PD_DEMO_PASSENGER_TOKEN='<random independent token, at least 32 chars>'
export PD_DEMO_PILOT_TOKEN='<random independent token, at least 32 chars>'
export PD_DEMO_DISPATCHER_TOKEN='<random independent token, at least 32 chars>'
export PD_DEMO_DB='/tmp/private-drive-isolated-demo.sqlite'
python3 test_sync_server/pd_demo_server.py
```

The server listens at `127.0.0.1:8765` by default. This address is not
reachable from separate physical phones. **Do not expose port 8765 to the
Internet or bind the server to 0.0.0.0.** To test across real devices, a
separate temporary TLS-terminating reverse proxy on a trusted development
network is required. Configure a trusted HTTPS certificate, isolate the
network, enforce rate limits and delete test credentials/database afterward.
No public tunnel is started by CI. An optional, explicitly approved,
20-minute Quick Tunnel launcher is available for synthetic cross-device tests.

Open the application's **test interface** → **Тестовая связь между
устройствами**. On each phone use the same isolated HTTPS proxy URL and the
distinct passenger, pilot or dispatcher token. Verify the sequence:
for the optional Quick Tunnel launcher, a synthetic trip is created and
assigned to `pilot_test` automatically before the URL is shown. Both phone
sessions can immediately exchange messages in the isolated chat. The manual
server-only setup above does not create this trip automatically. Pilot status
transitions, if tested, must use the isolated API, not production dispatch. Reconnect
after restarting the client to verify server-side recovery.

## Offline API smoke-test

```sh
PYTHONPATH=test_sync_server python3 -m unittest discover \
  -s test_sync_server -p 'test_*.py' -v
```

Endpoints (all require bearer auth):

| Method | Endpoint | Allowed role |
| --- | --- | --- |
| GET | `/v1/me` | all |
| GET | `/v1/current` | all; only visible trip |
| POST | `/v1/trips` | passenger |
| GET | `/v1/trips/{id}` | owner, assigned pilot, dispatcher |
| GET | `/v1/trips/{id}/events?after=N` | same as above |
| POST | `/v1/trips/{id}/assign` | dispatcher |
| POST | `/v1/trips/{id}/action` | assigned pilot |

Statuses: `requested → assigned → approaching → underway → finished`.
`pause` and `resume` keep the current stage. Every mutation requires the
latest integer `version`; `409 version_conflict` means refresh first.

**Not a production-ready dispatch service.** It has single-purpose static
test principals, no account provisioning, durable client credentials or
device push, and no tested remote deployment, load balancing or abuse
protection. Never substitute its bearer tokens or test SQLite for actual
authenticated customer accounts. Location and OSM tile usage must also be
validated under real mobile conditions separately.

## Option A — no-cost temporary HTTPS for two phones (Windows 11)

Cloudflare Quick Tunnel creates an ephemeral public HTTPS hostname, without a
Cloudflare account or domain. It has **no uptime guarantee** and the hostname
may change on restart. It is a public endpoint, NOT a private VPN. Only
random disposable tokens and synthetic addresses may be used.

Prerequisites: Python 3 and the official cloudflared program.

```powershell
winget install --id Cloudflare.cloudflared --exact
$env:PD_DEMO_PUBLIC_TUNNEL = "YES"
py -3 test_sync_server/run_quick_tunnel.py
```

The launcher explicitly refuses to run without the YES opt-in; it creates a
temporary SQLite database, three independent random role credentials and a
localhost-only backend, then creates one **synthetic assigned chat trip** for
passenger_test and pilot_test. It starts cloudflared and prints the test HTTPS
URL, temporary tokens and the short test trip ID.
It stops the server and tunnel automatically after 20 minutes or Ctrl+C and
deletes the temporary database. The developer PC must stay running during
the session. Do not paste real user addresses or production secrets.

**Security**: TLS terminates at Cloudflare; the provider may process HTTP
headers including test bearer tokens. This is appropriate only for dummy
credentials and synthetic data. Cloudflare Protected Quick Tunnels use an
email OTP interstitial which this native bearer-only client does not support;
do not combine them without implementing a compatible native Access flow.

## Option B — private HTTPS for a personal evaluation

Tailscale Serve can publish HTTPS exclusively inside an authenticated
tailnet. The Tailscale free *Personal* tier is for eligible personal use,
not assumed suitable for commercial PRIVATE DRIVE activities; verify plan
eligibility/terms before selecting it. A tailnet requires its client
on the server PC and both phones, and HTTPS certificates enabled. This
project does not enroll devices or alter Tailscale access policies.

## Two-phone manual verification (without production)

1. Run the isolated launcher on a throwaway development PC, then keep it
   open. Do not use the live PythonAnywhere host or real account details.
2. On Android, install the debug APK from the matching feature-branch CI
   artifacts. Open the test interface, select remote sync, supply the HTTPS
   URL and the PASSENGER role token printed by the launcher. Create an
   invented route, for example 'Тест A' -> 'Тест B'.
3. For dispatcher assignment use a separate test client (e.g. a second
   Android debug device/emulator) with the DISPATCHER token. Assign
   'pilot_test'. A pilot client with the PILOT token advances, pauses,
   resumes and finishes the fake trip. Roles must never share a token.
4. The present iOS CI produces **unsigned** Debug/Release builds; an iPhone
   cannot install them without legitimate Apple code signing. As a partial
   iPhone network-only check, create an Apple Shortcut with 'Get Contents
   of URL' pointing to the HTTPS_URL + '/v1/current', choose GET, add
   header 'Authorization' = 'Bearer ' + the appropriate *test* token,
   and inspect the returned JSON status. This does NOT validate the iOS
   Flutter interface. Avoid sharing shortcuts containing token values.
5. Refresh the passenger view after each stage and confirm the status
   changes. Reopen the native test screen and re-enter credentials: the
   synthetic trip is restored from the temporary server SQLite while
   the launcher remains running. A full server restart resets this
   disposable launcher database by design; persistent SQLite restart
   recovery is covered separately by automated server tests.
6. Verify wrong-token 401, forbidden role 403, unassigned pilot 404, stale
   version 409, and a stopped tunnel becoming unreachable. Stop with
   Ctrl+C and dispose of the temporary role tokens.

## Automated offline networking checks

```powershell
python -m unittest discover -s test_sync_server -p 'test_*.py' -v
```

Network integration tests generate a temporary TLS certificate (requires
OpenSSL), use client-verified HTTPS, test an untrusted certificate,
exercise three separate role clients, concurrent version conflicts and
SQLite restart recovery. The CI runner intentionally never calls
trycloudflare.com, registers accounts, or launches a live public tunnel.

**Remaining blockers before a true iPhone ↔ Android mobile app test:**
signing/installing an iOS test build with an authorized Apple account,
access to two physical devices, and a manually approved temporary HTTPS
session. Production security/rate limits and real authentication are
outside this synthetic test scope.
