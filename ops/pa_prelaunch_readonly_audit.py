"""Read-only prelaunch audit of LIVE PRIVATE DRIVE sources and public API.

Does not import or execute production modules, inspect customer DB records, send
Telegram messages, create bookings, call payment POST endpoints, or reload server.
Prints only structural findings, counters, HTTP codes and safe boolean results.
"""
import ast
import hashlib
import os
import re
import sys
from collections import defaultdict

import requests

USER = "wilsonpark"
ROOT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
HOST = "https://www.pythonanywhere.com/api/v0/user/" + USER
SITE = "https://wilsonpark.pythonanywhere.com"
FILES = [
    "miniapp/templates/index.html",
    "miniapp_server.py",
    "Euro_Baltic_Transfer.py",
    "pd_trip_runtime_v4.py",
    "pd_trip_runtime_v4.js",
    "pd_pilot_cabinet_v4.js",
    "pd_pilot_dispatch.py",
    "pd_admin_console_v4.js",
    "pd_admin_console_v4.py",
    "pd_fixed_prices.py",
    "pd_onboarding.py",
    "pd_prepayment_v3.py",
    "pd_prepayment_v3.js",
]
TEST_ENDPOINTS = [
    "/",
    "/privacy",
    "/legal",
    "/api/me",
    "/api/orders",
    "/api/driver/work",
    "/api/admin/orders",
    "/api/admin/pilot-assignments",
]
TOKEN = "".join(re.sub(r"^Token\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I).split())
if not TOKEN:
    raise SystemExit("AUDIT_BLOCKED: no access token configured")

session = requests.Session()
session.headers["Authorization"] = "Token " + TOKEN
source = {}
warnings = []
failures = []

def heading(s):
    print("SECTION", s)

heading("PythonAnywhere read-only source inventory")
for path in FILES:
    try:
        response = session.get(HOST + "/files/path" + ROOT + "/" + path, timeout=30)
    except requests.RequestException:
        failures.append("REMOTE_FETCH_ERROR " + path)
        continue
    if response.status_code == 404:
        warnings.append("SOURCE_NOT_FOUND " + path)
        continue
    if response.status_code != 200:
        failures.append("REMOTE_HTTP " + path + " " + str(response.status_code))
        continue
    try:
        text = response.content.decode("utf-8", "strict")
    except UnicodeDecodeError:
        failures.append("INVALID_UTF8 " + path)
        continue
    source[path] = text
    print("SOURCE_OK", path, "bytes", len(response.content),
          "sha256_12", hashlib.sha256(response.content).hexdigest()[:12])
    if path.endswith(".py"):
        try:
            ast.parse(text, filename=path)
            print("SYNTAX_OK", path)
        except SyntaxError:
            failures.append("PY_SYNTAX " + path)

heading("Passenger / pilot / dispatcher UI")
html = source.get("miniapp/templates/index.html", "")
jstext = "\n".join(v for p, v in source.items() if p.endswith(".js")) + "\n" + html
inline = re.findall(r"""(?i)\bonclick\s*=\s*["']([^"']+)["']""", html)
names = sorted(set(m.group(1) for a in inline if (m := re.match(r"\s*([a-zA-Z_$][\w$]*)\s*\(", a))))
print("INLINE_CLICK_ATTRIBUTES", len(inline), "UNIQUE_SIMPLE_HANDLERS", len(names))
missing = []
for name in names:
    if not re.search(r"\bfunction\s+" + re.escape(name) + r"\b|\b(?:const|let|var)\s+"
                     + re.escape(name) + r"\b|\b" + re.escape(name)
                     + r"\s*=\s*(?:async\s*)?function|\bwindow\." + re.escape(name) + r"\b", jstext):
        missing.append(name)
print("MISSING_HANDLER_DECLARATIONS", len(missing))
# Names only, never dump source lines, customer content or variables.
if missing:
    print("MISSING_NAMES", ",".join(missing[:15]))
    warnings.append("BUTTON_HANDLERS_MISSING")

expected = {
    "passenger": ["pdbSendOrder", "pdbCalculate", "pdbLocate", "pdbRegisterTelegram"],
    "pilot": ["pdEnterPilot", "pdPilotWork", "pdOpenLiveTripV4"],
    "dispatcher": ["pdSwitchTab", "pdAssignPilot", "pdBankConfirm"],
}
for role, handlers in expected.items():
    found = [x for x in handlers if re.search(r"\b" + x + r"\b", jstext)]
    print("ROLE_UI", role, "expected", len(handlers), "found", len(found),
          "missing", ",".join(x for x in handlers if x not in found) or "-")
    if len(found) < len(handlers):
        warnings.append("ROLE_HANDLERS_NOT_ALL_PRESENT_" + role)

tripjs = source.get("pd_trip_runtime_v4.js", "")
print("TRIP_BUTTONS", "arrival", bool(re.search(r"arrive|Прибыл", tripjs)),
      "start", bool(re.search(r"start|Начать поездку", tripjs)),
      "finish", bool(re.search(r"finish|Заверш", tripjs)),
      "stop", "Остановка" in tripjs)
print("GPS_CLIENT", "watchPosition", "watchPosition" in tripjs,
      "clearWatch", "clearWatch" in tripjs,
      "stopOnClose", "function cleanDialog(){stopPosition();" in tripjs,
      "stopOnBackground", "visibilitychange" in tripjs)
print("UI_FARE", "approved200", "return '200.00' if data.get('roundtrip')" in source.get("pd_fixed_prices.py", ""),
      "old190", "return '190.00' if data.get('roundtrip')" in source.get("pd_fixed_prices.py", ""))
print("LEGACY_TEMPERATURE", "present" if "Температура в салоне" in html else "absent")

heading("API registration and source-level security controls")
pyall = "\n".join(v for p, v in source.items() if p.endswith(".py"))
for endpoint in ["/api/me", "/api/register", "/api/order", "/api/orders", "/api/driver/work",
                 "/api/admin/orders", "/api/admin/pilot-assignments", "/api/trip/",
                 "/api/admin/trip/"]:
    print("API_ROUTE_DECLARED", endpoint, bool(endpoint in pyall))
for label, pattern in [
    ("telegram_init_auth", r"X-Telegram-Init-Data|init_data"),
    ("admin_gate", r"is_admin\s*\("),
    ("pilot_gate", r"pilot_access|approved\s*\("),
    ("booking_idempotency", r"request_key"),
    ("trip_action", r"/action"),
]:
    print("SECURITY_MARKER", label, bool(re.search(pattern, pyall)))
# Markers are not a security-proof; isolated behavioral tests remain necessary.

heading("Non-mutating public endpoint response checks")
public = requests.Session()
for endpoint in TEST_ENDPOINTS:
    try:
        r = public.get(SITE + endpoint, timeout=20, allow_redirects=False,
                       headers={"Cache-Control": "no-cache"})
        print("PUBLIC_GET", endpoint, "HTTP", r.status_code)
        if endpoint in ("/", "/privacy", "/legal") and r.status_code != 200:
            warnings.append("PUBLIC_PAGE_NOT_200 " + endpoint)
        if endpoint.startswith("/api/") and r.status_code not in (400, 401, 403):
            warnings.append("AUTH_BOUNDARY_REVIEW " + endpoint + " HTTP_" + str(r.status_code))
    except requests.RequestException:
        warnings.append("PUBLIC_REQUEST_FAILED " + endpoint)

heading("Final read-only assessment")
for item in sorted(set(warnings)):
    print("WARN", item)
for item in sorted(set(failures)):
    print("FAIL", item)
print("AUDIT_SUMMARY", "files", len(source), "warnings", len(set(warnings)),
      "fatal", len(set(failures)), "writes", 0, "bookings_created", 0, "payments", 0)
if failures:
    sys.exit(2)
