"""Install the single-order dispatcher test entry in the existing Mini App."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import time

from jinja2 import Environment
import requests

HOST = "https://www.pythonanywhere.com/api/v0/user/wilsonpark"
SITE = "https://wilsonpark.pythonanywhere.com"
SOURCE = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
STAGING = "https://private-drive-dispatcher-staging.onrender.com/preview/telegram-miniapp"
MARKER = 'id="pdTelegramDispatchTest"'
PREVIOUS_FRAGMENT_SHA = "55931ec084fbe1d8c59f6ab4c02e8ecec0061a7ea2eee6ceeedbe6a2777a4e44"
PREVIOUS_FRAGMENT = re.compile(
    r'<details id="pdTelegramDispatchTest"[^>]*>[\s\S]*?'
    r'<script id="pdTelegramDispatchTestScript">[\s\S]*?</script>'
)
HEADING = re.compile(r'<section\b[^>]+\bid=["\']step10["\'][^>]*>\s*<h2\b[^>]*>[^<]*Диспетчерская[^<]*</h2>')


def with_fragment(source, fragment):
    if source.count(MARKER) == 1 and fragment in source:
        return source
    if MARKER in source:
        existing = list(PREVIOUS_FRAGMENT.finditer(source))
        if (source.count(MARKER) != 1 or len(existing) != 1
                or hashlib.sha256(existing[0].group().encode()).hexdigest() != PREVIOUS_FRAGMENT_SHA):
            raise RuntimeError("Telegram dispatcher fragment already exists in an unexpected form")
        return source[:existing[0].start()] + fragment.rstrip("\n") + source[existing[0].end():]
    matches = list(HEADING.finditer(source))
    if len(matches) != 1:
        raise RuntimeError("Dispatcher heading changed")
    end = matches[0].end()
    return source[:end] + "\n" + fragment + source[end:]


def api(session, method, path, **kwargs):
    for attempt in range(3):
        response = session.request(method, HOST + path, timeout=38, **kwargs)
        if response.status_code != 429 or attempt == 2:
            if not response.ok:
                raise RuntimeError(f"Hosting {method} returned HTTP {response.status_code}")
            return response
        time.sleep(8 * (attempt + 1))


def main():
    fragment = Path(__file__).with_name("telegram_dispatch_test_fragment.html").read_text()
    js = fragment.split('<script id="pdTelegramDispatchTestScript">', 1)[1].split("</script>", 1)[0]
    subprocess.run(["node", "--check"], input=js, text=True, check=True)
    for _ in range(18):
        response = requests.options(STAGING, headers={
            "Origin": SITE, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-telegram-init-data",
        }, timeout=20)
        if response.ok and response.headers.get("Access-Control-Allow-Origin") == SITE:
            break
        time.sleep(5)
    else:
        raise RuntimeError("Staging API did not approve the Mini App origin")
    login = requests.get(SITE + "/dispatch", timeout=20)
    login.raise_for_status()
    if login.url != SITE + "/dispatch/login" or 'type="password"' not in login.text:
        raise RuntimeError("Working dispatcher login is unavailable")
    baseline = requests.get(SITE, timeout=20)
    baseline.raise_for_status()
    if not HEADING.search(baseline.text):
        raise RuntimeError("The public Mini App no longer matches the expected dispatcher heading")

    token = re.sub(r"^Token\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I)
    if not token:
        raise RuntimeError("PythonAnywhere API credential is unavailable")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not run_id.isdecimal():
        raise RuntimeError("GitHub run ID is unavailable")
    backup = f"/home/wilsonpark/private_drive_backups/telegram_dispatch_test_{run_id}.html"
    with requests.Session() as session:
        session.headers.update({"Authorization": "Token " + token})
        def read(path):
            return api(session, "GET", "/files/path" + path).content
        def write(path, value):
            api(session, "POST", "/files/path" + path,
                files={"content": ("template.html", value, "text/html")})
            if read(path) != value:
                raise RuntimeError("Template readback differs")
        original = read(SOURCE)
        original_text = original.decode("utf-8")
        updated = with_fragment(original_text, fragment)
        Environment().parse(updated)
        if updated == original_text:
            if MARKER not in baseline.text or 'Открыть рабочую диспетчерскую на сайте' not in baseline.text:
                raise RuntimeError("Saved template and public Mini App differ")
            print("Already live")
            return
        write(backup, original)
        if read(SOURCE) != original:
            raise RuntimeError("Concurrent template edit")
        candidate = updated.encode("utf-8")
        try:
            write(SOURCE, candidate)
            try:
                api(session, "POST", "/webapps/wilsonpark.pythonanywhere.com/reload/")
            except requests.exceptions.ReadTimeout:
                pass
            for _ in range(6):
                published = requests.get(SITE, params={"pd_dispatch_deploy": run_id}, timeout=23)
                if (published.ok and published.text.count(MARKER) == 1
                        and "id=\"pdObPassenger\"" in published.text
                        and "id=\"pdPilotWork\"" in published.text
                        and STAGING in published.text
                        and 'Открыть рабочую диспетчерскую на сайте' in published.text):
                    print("Mini App entry verified. Original SHA-256:", hashlib.sha256(original).hexdigest())
                    return
                time.sleep(3)
            raise RuntimeError("The public Mini App did not show the expected entry")
        except BaseException:
            current = read(SOURCE)
            if current not in (original, candidate):
                raise RuntimeError("Concurrent edit detected after deployment")
            if current == candidate:
                write(SOURCE, original)
                try:
                    api(session, "POST", "/webapps/wilsonpark.pythonanywhere.com/reload/")
                except requests.exceptions.ReadTimeout:
                    pass
            raise


if __name__ == "__main__":
    main()
