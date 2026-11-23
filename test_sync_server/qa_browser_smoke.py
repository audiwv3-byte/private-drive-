"""Headless QA browser smoke: real Flutter Web, isolated Mock API, no credentials in logs."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

address = os.environ["PD_MOCK_CABINET_API_URL"].rstrip("/")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    failures = []
    request_statuses = []
    page.on("pageerror", lambda err: failures.append(str(err)[:300]))
    page.on("response", lambda response: request_statuses.append(response.status)
            if response.url.endswith("/native-auth/qa-session") else None)
    try:
        page.goto(address + "/app/", wait_until="domcontentloaded", timeout=30000)
        page.locator("flt-semantics-placeholder").click(timeout=12000)
        page.get_by_text("Пассажир", exact=True).first.click(timeout=35000)
        page.get_by_text("Я ознакомился с условиями сервиса", exact=False).first.click(timeout=15000)
        page.get_by_text("Войти в тестовый кабинет без SMS").click(timeout=15000)
        page.get_by_text("Выбери тип поездки", exact=False).wait_for(timeout=20000)
        assert request_statuses == [200], "Synthetic QA session failed HTTP verification"
        assert not failures, "Browser runtime error: " + repr(failures)
        print("PASS: actual Chromium Flutter Web signs in via synthetic session and opens passenger cabin")
    except Exception:
        Path("device_artifacts/browser").mkdir(parents=True, exist_ok=True)
        page.screenshot(path="device_artifacts/browser/qa-login-failure.png", full_page=True)
        print("QA login response statuses:", request_statuses)
        print("Browser errors:", failures[:3])
        raise
    finally:
        browser.close()
