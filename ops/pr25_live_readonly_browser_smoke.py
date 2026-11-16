"""Read-only browser smoke after PR25. Never creates orders or payments."""
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

BASE = "https://wilsonpark.pythonanywhere.com"
HOST = urlsplit(BASE).netloc

def check(browser, name, viewport, mobile=False):
    context = browser.new_context(
        viewport=viewport, device_scale_factor=1,
        is_mobile=mobile, has_touch=mobile,
        locale="ru-RU", service_workers="block",
    )
    page = context.new_page()
    errors, blocked = [], []
    page.on("pageerror", lambda e: errors.append(str(e)[:160]))
    def only_readonly(route):
        req = route.request
        url = urlsplit(req.url)
        if req.method != "GET":
            blocked.append(req.method)
            route.abort("blockedbyclient")
        elif url.netloc != HOST:
            route.abort("blockedbyclient")
        elif url.path.startswith("/api/"):
            # Authenticated actions are out of scope. API GET access is checked
            # separately using requests without any session or identity.
            route.abort("blockedbyclient")
        else:
            route.continue_()
    page.route("**/*", only_readonly)
    response = page.goto(BASE + "/", wait_until="domcontentloaded", timeout=35000)
    assert response and response.status == 200, "MAIN_PAGE_NOT_200"
    page.wait_for_timeout(1800)
    source = page.content()
    assert "PRIVATE DRIVE" in source.upper(), "BRAND_MISSING"
    selectors = ["input", "button", "select", "textarea", "[role=button]"]
    counts = {sel: page.locator(sel).count() for sel in selectors}
    assert sum(counts.values()) >= 5, "INTERFACE_CONTROLS_MISSING"
    terms = ["gps", "pil", "driver", "dispatcher", "admin", "route", "payment", "оплат", "пилот", "маршрут", "диспетчер"]
    present = [term for term in terms if term in source.lower()]
    assert len(present) >= 3, "EXPECTED_ROLES_AND_TRIP_TEXT_MISSING"
    # Only raw source/visible elements were inspected; no role/login interactions.
    assert not blocked, "UNEXPECTED_WRITE_ATTEMPT"
    assert not errors, "JAVASCRIPT_ERRORS_" + json.dumps(errors[:3],ensure_ascii=False)
    print("LIVE_UI_PASS",name,"HTTP",response.status,"CONTROLS",counts,
          "TERMS",",".join(present),"JS_ERRORS",len(errors),
          "MUTATING_REQUESTS",len(blocked),flush=True)
    context.close()

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    check(browser,"MOBILE",{"width":390,"height":844},True)
    check(browser,"DESKTOP",{"width":1365,"height":900})
    browser.close()
print("PR25_LIVE_READONLY_BROWSER_SMOKE_PASSED",flush=True)
