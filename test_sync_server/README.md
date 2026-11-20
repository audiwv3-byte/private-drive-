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
- Browser-origin requests are denied by default. A **single explicit**
  `PD_DEMO_BROWSER_ORIGIN=https://your-test-netlify-host.netlify.app` allows
  authenticated Safari Web preview calls with a restricted CORS preflight.
  There is no wildcard origin, cookie auth or browser admin panel. Requests
  never expose bearer tokens in logs.
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

## Проверка связи на двух физических Android-телефонах (только DEMO)

**Предусловия:** на обоих Android установлена проверенная APK из ветки
`feature/flutter-independent-auth`. На отдельном тестовом Windows-ПК
имеются Python 3 и официальный `cloudflared`. Этот ПК не является
production-сервером. Два телефона могут находиться в разных сетях.

1. В PowerShell из корня тестового репозитория запусти
   `$env:PD_DEMO_PUBLIC_TUNNEL = "YES"; py -3 test_sync_server/run_quick_tunnel.py`.
   Включение публичного HTTPS-туннеля требует этой **явной** команды; CI
   туннель не запускает. Не публикуй URL и токены в чатах или скриншотах.
2. После появления `HTTPS URL` тестовый сервер уже создал **один
   вымышленный заказ** и назначил `pilot_test`. Создавать заказ, нажимать
   «Оплатить» или назначать пилота вручную **не нужно**.
3. Телефон A: войди в кабинет **пассажира**, открой **«Тестовая связь между
   устройствами»**, укажи адрес `HTTPS URL`, затем `PASSENGER TEST TOKEN`.
   Нажми **«Подключить тестовый чат»**.
4. Телефон B: открой **Кабину пилота**, левое меню → тестовый чат.
   Используй **тот же HTTPS URL**, но `PILOT TEST TOKEN`.
   Нажми **«Подключить тестовый чат»**.
5. Оба телефона должны показать один и тот же сокращённый ID тестового заказа.
   Отправь **«Тест: пассажир на месте»** из A и убедись, что текст виден
   в B. Затем отправь **«Тест: пилот подъезжает»** из B и убедись, что
   текст виден в A. Обнови обе переписки: сообщения не должны дублироваться.
6. Закрой и открой экран тестового чата, подключись заново с теми же
   временными токенами — оба сообщения должны восстановиться из SQLite
   текущего сеанса. После полной перезагрузки лаунчера данные
   **не восстанавливаются**: создаётся новый одноразовый сеанс.
7. Заверши тест клавишами `Ctrl+C` на ПК (или дождись автоматического
   завершения через 20 минут). Убедись, что HTTPS URL больше не отвечает.
   Лаунчер завершает процессы и удаляет временную SQLite-базу.

**Критерии приёмки:** оба клиента подключились по HTTPS, получили один заказ,
обменялись сообщениями в обе стороны, не увидели дубликатов, восстановили
историю при переподключении и потеряли доступ после завершения сеанса.

**Ограничения:** Quick Tunnel — временный **публичный** HTTPS-адрес, а не
приватная VPN. Cloudflare терминирует TLS. Для эксперимента используй только
одноразовые токены и вымышленные сообщения; не вводи реальные имена,
маршруты, адреса, телефоны, платежи или ключи. Реальное соединение двух
физических телефонов **не подтверждается одними CI-тестами**. Доступ к ним
и ручной запуск сеанса нужны отдельно.

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

## One-shot Safari ↔ Android demo using the existing Windows PC

The test-only Quick Tunnel launcher now **automatically** sets
`PD_DEMO_BROWSER_ORIGIN=https://luxury-mochi-84e459.netlify.app`.
No Netlify setting, DNS record or production server changes are needed.
Do not set any alternative `PD_DEMO_BROWSER_ORIGIN` value; the launcher
fails closed rather than exposing the demo to another browser host.

From a current checkout of `feature/flutter-independent-auth`, run
the following in Windows PowerShell, after installing the official
`cloudflared` client and Python 3:

```powershell
$env:PD_DEMO_PUBLIC_TUNNEL = "YES"
py -3 test_sync_server/run_quick_tunnel.py
```

The terminal prints the temporary Cloudflare HTTPS URL and disposable
`PASSENGER TEST TOKEN` / `PILOT TEST TOKEN`. Enter the URL and passenger
token in **Safari** at
`https://luxury-mochi-84e459.netlify.app`. The existing Android demo
pilot's isolated chat uses the **same URL** and the **pilot token**.
Never paste these tokens into public chat, GitHub, screenshots or a
production app, and never send real customer data. The test ends after
20 minutes and removes the disposable SQLite database. The desktop
running the script must remain online during the test.

Neither GitHub Actions nor the Netlify static site runs a persistent
HTTP API. The isolated server cannot work across phones until a
dedicated testing machine starts it. CI synthetic messaging tests do
not prove the actual two-device session or Safari tile rendering.

## Safari Web preview (isolated API only)

The test Netlify build uses `PD_ISOLATED_WEB_PREVIEW=true` and opens the
`RemoteSyncDemo` screen instead of SMS authentication. Its public static
bundle includes **no** bearer token and **no** server URL. Supply the exact
HTTPS address and a temporary role token on the test screen.

For a browser API call, the isolated backend must start with
`PD_DEMO_BROWSER_ORIGIN` set to the **exact origin** of the test Web
preview (HTTPS, hostname only, no trailing slash). A separate trusted HTTPS
reverse proxy or the explicitly approved disposable tunnel must deliver the
API. Native Android clients have no browser Origin header and continue to use
independent role tokens. A preflight from an unapproved origin is rejected.

Open the same synthetic trip from two devices: Safari passenger with the
passenger token; Android pilot with the pilot token. The remote test screen
polls server messages and trip status every 3 seconds. Its OSM map is shown
for passenger and pilot, and a backup tile source plus an error/retry UI are
provided. The ordinary offline DEMO cabins remain local and **do not** sync.

**Important:** CI proves API and widget behavior with synthetic identities;
it cannot certify real iPhone Safari image loading or physical-device delivery.
Nothing in this workflow publishes to Netlify or production automatically.
Do not enter real addresses, phone numbers, payments or production tokens.
