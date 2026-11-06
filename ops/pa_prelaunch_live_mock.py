"""Pull LIVE source into an ephemeral CI tempdir and run MOCK-ONLY JS tests.

Read-only PythonAnywhere GET calls; node tests use vm with synthetic responses.
No production databases, Telegram credentials or payment keys are downloaded.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import requests

USER = "wilsonpark"
ROOT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
BASE = f"https://www.pythonanywhere.com/api/v0/user/{USER}/files/path{ROOT}/"
NEEDED = [
    "miniapp/templates/index.html",
    "pd_trip_runtime_v4.js",
    "pd_pilot_cabinet_v4.js",
    "pd_admin_console_v4.js",
    "pd_prepayment_v3.js",
    "pd_invoice_v2.js",
]
TOKEN = "".join(re.sub(r"^Token\s+", "", os.getenv("PA_API_TOKEN", "").strip(), flags=re.I).split())
if not TOKEN:
    sys.exit("TEST_BLOCKED: missing credential")
session = requests.Session()
session.headers["Authorization"] = "Token " + TOKEN
source_root = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="pd-live-mock-test-") as work:
    root = Path(work)
    for name in NEEDED:
        r = session.get(BASE + name, timeout=40)
        if r.status_code != 200:
            sys.exit("TEST_BLOCKED: cannot read required live file " + name
                     + " HTTP " + str(r.status_code))
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(r.content)
        print("LIVE_TEST_SOURCE", name, "bytes", len(r.content),
              "sha256_12", hashlib.sha256(r.content).hexdigest()[:12], flush=True)
    test = source_root / "test_miniapp_interactions.cjs"
    if not test.is_file():
        sys.exit("TEST_BLOCKED: missing approved mock test")
    (root / "test_miniapp_interactions.cjs").write_bytes(test.read_bytes())
    # No token, project secrets or production path is exposed to Node.
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": work}
    p = subprocess.run(
        ["node", "--unhandled-rejections=strict", "test_miniapp_interactions.cjs"],
        cwd=root, env=env, text=True, capture_output=True, timeout=50,
    )
    # These scripts contain only fixed PASS strings and assertion names;
    # sanitize to avoid revealing source-derived content on exceptions.
    for line in p.stdout.splitlines():
        if line.startswith("PASS "):
            print("LIVE_MOCK", line)
    if p.returncode:
        print("LIVE_MOCK_FAILED exit", p.returncode)
        for line in p.stderr.splitlines():
            if line.lstrip().startswith(("AssertionError", "Error:", "TypeError:",
                                        "ReferenceError:", "SyntaxError:")):
                print("DIAGNOSTIC", line[:250])
        sys.exit(1)
    print("LIVE_MOCK_SUCCESS: source executed with synthetic DOM, trip and GPS API")
