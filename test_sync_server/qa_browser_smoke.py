"""Smoke-test the compiled QA app against its isolated HTTPS Mock API."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def flutter_text(page, label, *, exact=True):
    operator = "=" if exact else "^="
    return page.get_by_text(label, exact=exact).or_(
        page.locator(f'[aria-label{operator}"{label}"]')
    ).first


def smoke(browser_type, device):
    with browser_type.launch(headless=True) as browser:
        page = browser.new_page(**device)
        statuses = []
        errors = []

        def record(response):
            path = response.url.removeprefix(ADDRESS)
            if path in {"/native-auth/qa-session", "/v1/me", "/v1/current"}:
                statuses.append((path, response.status))

        page.on("response", record)
        page.on("pageerror", lambda error: errors.append(str(error)[:300]))
        try:
            page.goto(ADDRESS + "/app/", wait_until="domcontentloaded", timeout=30000)
            page.locator("flt-semantics-placeholder").click(timeout=35000)
            flutter_text(page, "Пассажир").click(timeout=20000)
            flutter_text(page, "Я ознакомился с условиями сервиса", exact=False).click(timeout=20000)
            taxi = page.locator('[flt-semantics-identifier="passenger-entry-taxi"]')
            with page.expect_response(ADDRESS + "/v1/current", timeout=20000) as entered:
                flutter_text(page, "Войти в тестовый кабинет без SMS").click(timeout=20000)
            assert entered.value.ok, statuses
            taxi.wait_for(state="attached", timeout=15000)
            assert statuses.count(("/native-auth/qa-session", 200)) == 1, statuses
            assert statuses.count(("/v1/me", 200)) == 2, statuses

            with page.expect_response(ADDRESS + "/v1/current", timeout=30000) as restored:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            assert restored.value.ok, statuses
            page.locator("flt-semantics-placeholder").click(timeout=20000)
            taxi.wait_for(state="attached", timeout=15000)
            assert statuses.count(("/native-auth/qa-session", 200)) == 1, statuses
            assert statuses.count(("/v1/me", 200)) == 4, statuses
            assert not errors, errors
            print(f"PASS: {browser_type.name} opened passenger cabin and restored its Bearer session")
        except Exception:
            folder = Path("device_artifacts/browser")
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=folder / f"{browser_type.name}-login-failure.png", full_page=True)
            print("QA request statuses:", statuses, "Browser errors:", errors[:3])
            print("Visible semantics:", page.locator("flt-semantics").evaluate_all(
                """nodes => nodes.map(node => node.getAttribute('aria-label'))
                  .filter(label => label).slice(-25)"""))
            raise


ADDRESS = os.environ["PD_MOCK_CABINET_API_URL"].rstrip("/")
with sync_playwright() as playwright:
    smoke(playwright.webkit, playwright.devices["iPhone 13"])
    smoke(playwright.chromium, playwright.devices["Pixel 7"])
