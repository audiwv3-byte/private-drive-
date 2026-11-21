"""Playwright mobile regression for isolated PRIVATE DRIVE preview, no actual orders."""
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
import time

BASE = "http://127.0.0.1:8765"
for _ in range(50):
    try:
        with urlopen(BASE + "/", timeout=1) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(0.4)
else:
    raise AssertionError("staging Flask unavailable")

Path("mobile-qa-screenshots").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for width, height in [(320, 720), (390, 844), (768, 1024), (1280, 850)]:
        page = browser.new_page(viewport={"width":width, "height":height}, device_scale_factor=1)
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        page.route("https://unpkg.com/**", lambda route: route.abort())
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        for name in ("hero", "airport", "kaunas", "klaipeda", "warsaw",
                     "service_airport", "service_parcel", "service_driver"):
            image = page.locator('img[src="/assets/pd-approved-' + name + '.webp"]')
            assert image.count() == 1, f"{name} absent on {width}px"
            image.scroll_into_view_if_needed()
            image.evaluate("(img) => img.loading = 'eager'")
            page.wait_for_function("""(name) => {
              const image=document.querySelector('img[src="/assets/pd-approved-' + name + '.webp"]');
              return image && image.complete && image.naturalWidth > 300;
            }""", arg=name, timeout=10000)
        info = page.evaluate("""() => ({
           viewport:innerWidth, pageWidth:document.documentElement.scrollWidth,
           serviceCards:document.querySelectorAll('.pd-services-three .pd-img-card').length,
           fareCards:document.querySelectorAll('.pd-destinations .fare-link').length,
           booking:!!document.getElementById('passenger-preview'),
           map:!!document.getElementById('order-live-map')
        })""")
        assert info["pageWidth"] <= width + 2, f"Horizontal overflow at {width}: {info}"
        assert info["serviceCards"] == 3 and info["fareCards"] == 4, info
        # Main banner must use the owner's saved RAV4 photo with no unrelated person.
        assert page.locator('.pd-hero-img[src="/assets/pd-user-photo-6-original.webp"]').count() == 1
        assert page.locator('.pd-hero-img[src="/assets/pd-approved-hero.webp"]').count() == 0
        hero = page.locator(".pd-hero-img")
        hero.scroll_into_view_if_needed()
        assert hero.evaluate("(img) => img.complete && img.naturalWidth >= 800")

        # Approved screenshot uses light sections, dark/navy hero and compact footer.
        visual = page.evaluate("""() => ({
            sectionBg: getComputedStyle(document.querySelector('.pd-section')).backgroundColor,
            headingColor: getComputedStyle(document.querySelector('.pd-section h2')).color,
            heroBg: getComputedStyle(document.querySelector('.pd-hero')).backgroundImage,
            duplicateContactStrip: !!document.querySelector('.pd-contact-top'),
            duplicateServicesStrip: !!document.querySelector('.pd-extra')
        })""")
        assert visual["sectionBg"] == "rgb(247, 248, 251)", visual
        assert visual["headingColor"] == "rgb(20, 36, 59)", visual
        assert "gradient" in visual["heroBg"], visual
        assert not visual["duplicateContactStrip"] and not visual["duplicateServicesStrip"], visual
        page.locator(".pd-contacts-nav summary").click()
        assert page.locator('.pd-contacts-popup a[href="https://t.me/PrivateDraive"]').is_visible()
        assert page.locator('.pd-contacts-popup a[href="mailto:evrobaltictransfer@gmail.com"]').is_visible()
        menuBounds = page.locator(".pd-contacts-popup").bounding_box()
        assert menuBounds and menuBounds["x"] >= -2, menuBounds
        assert menuBounds["x"] + menuBounds["width"] <= width + 2, menuBounds
        page.locator(".pd-contacts-nav summary").click()

        assert info["booking"] and info["map"], info
        page.locator('a.fare-link[data-to="Каунас"]').click()
        assert page.locator("#quick-from").input_value() == "Вильнюс"
        assert page.locator("#quick-to").input_value() == "Каунас"
        page.locator("#quick-date").fill("2026-12-04")
        page.locator("#quick-time").fill("14:30")
        page.locator('#quick-trip-form button').click()
        assert page.locator("#pickup-address").input_value() == "Вильнюс"
        assert page.locator("#dropoff-address").input_value() == "Каунас"
        assert page.locator("#route-details").get_attribute("open") is not None
        assert page.locator("#pickup-date").input_value() == "2026-12-04"
        page.locator("header a[href='/services']").click()
        assert page.url.endswith("/services")
        assert page.locator("#jumpstart").count() == 1
        assert page.locator("#sober").count() == 1
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.screenshot(path=f"mobile-qa-screenshots/home-{width}.png", full_page=True)
        print(f"MOBILE_QA_OK width={width} images=8 services=3 fares=4 no_overflow=true quick_booking=true services_page=true", flush=True)
        page.close()
    browser.close()
