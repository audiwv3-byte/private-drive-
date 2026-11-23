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
        for name in ("airport", "kaunas", "klaipeda", "warsaw",
                     "service_airport", "service_parcel"):
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
        driver = page.locator('.pd-driver-card img')
        assert driver.count() == 1
        assert driver.get_attribute("src") == "/assets/pd-user-photo-6-original.webp"
        driver.scroll_into_view_if_needed()
        driver.evaluate("(img) => img.loading = 'eager'")
        page.wait_for_function("""() => {const img=document.querySelector('.pd-driver-card img');return img && img.complete && img.naturalWidth >= 800;}""", timeout=10000)
        assert page.locator('.pd-services-three img[src="/assets/pd-approved-service_driver.webp"]').count() == 0
        # Actual browser-calculated framing: original file remains unchanged, image
        # sits inside the driver card so its wheels cannot be lost to the 480:246 crop.
        crop = page.evaluate("""() => {
          const card=document.querySelector('.pd-driver-card'),
                driver=card.querySelector('img'), hero=document.querySelector('.pd-hero-img'),
                dStyle=getComputedStyle(driver), hStyle=getComputedStyle(hero);
          return {cardWidth:card.getBoundingClientRect().width,
                  imageWidth:driver.getBoundingClientRect().width,
                  driverPosition:dStyle.objectPosition,heroPosition:hStyle.objectPosition,
                  heroHeight:hero.getBoundingClientRect().height,
                  driverFit:dStyle.objectFit,heroFit:hStyle.objectFit};
        }""")
        assert 0.78 <= crop["imageWidth"]/crop["cardWidth"] <= 0.82, crop
        assert crop["driverFit"] == "cover" and crop["heroFit"] == "cover", crop
        assert crop["driverPosition"] == "50% 72%" and crop["heroPosition"] == "50% 72%", crop
        assert crop["heroHeight"] >= 245, crop
        # Readability and layout after the image crop (real Chromium geometry).
        ui = page.evaluate("""() => {
          const q=s=>document.querySelector(s);
          const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
          const title=q('.pd-hero h1'), hero=q('.pd-hero-img'),
                buttons=[...document.querySelectorAll('.pd-buttons a')],
                card=q('.pd-driver-card'), caption=q('.pd-driver-caption');
          const size=e=>parseFloat(getComputedStyle(e).fontSize);
          return {title:box(title),titleSize:size(title),photo:box(hero),
                  buttons:buttons.map(box),buttonFonts:buttons.map(size),
                  card:box(card),caption:box(caption),captionSize:size(caption)};
        }""")
        assert ui["titleSize"] >= 29 and ui["captionSize"] >= 13, ui
        assert len(ui["buttons"]) == 2 and all(b["h"] >= 44 for b in ui["buttons"]), ui
        assert all(font >= 14 for font in ui["buttonFonts"]), ui
        assert ui["photo"]["w"] >= 255 and ui["photo"]["h"] >= 245, ui
        assert ui["caption"]["x"] >= ui["card"]["x"] - 1, ui
        assert ui["caption"]["right"] <= ui["card"]["right"] + 1, ui
        assert ui["caption"]["bottom"] <= ui["card"]["bottom"] + 1, ui
        assert ui["title"]["x"] >= -1 and ui["title"]["right"] <= width + 1, ui
        print(f"RAV4_READABILITY_OK width={width} title_px={ui['titleSize']:.0f} card_caption_px={ui['captionSize']:.0f} hero_height={ui['photo']['h']:.0f} both_buttons>=44px", flush=True)



        # Main banner must use the owner's saved RAV4 photo with no unrelated person.
        assert page.locator('.pd-hero-img[src="/assets/pd-user-photo-6-original.webp"]').count() == 1
        assert page.locator('.pd-hero-img[src="/assets/pd-approved-hero.webp"]').count() == 0
        hero = page.locator(".pd-hero-img")
        hero.scroll_into_view_if_needed()
        assert hero.evaluate("(img) => img.complete && img.naturalWidth >= 800")

        # The requested black-and-gold palette covers sections, labels and inputs.
        visual = page.evaluate("""() => ({
            sectionBg: getComputedStyle(document.querySelector('.pd-section')).backgroundColor,
            headingColor: getComputedStyle(document.querySelector('.pd-section h2')).color,
            fieldBg: getComputedStyle(document.querySelector('#quick-from')).backgroundColor,
            heroBg: getComputedStyle(document.querySelector('.pd-hero')).backgroundImage,
            duplicateContactStrip: !!document.querySelector('.pd-contact-top'),
            duplicateServicesStrip: !!document.querySelector('.pd-extra')
        })""")
        assert visual["sectionBg"] == "rgb(16, 14, 11)", visual
        assert visual["headingColor"] == "rgb(237, 202, 130)", visual
        assert visual["fieldBg"] == "rgb(22, 18, 13)", visual
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
        # Browser-click every navigation item on narrow and wide viewports.
        for label, expected_hash in [("Главная", "#top"), ("Тарифы", "#prices"), ("О нас", "#about")]:
            page.locator(".pd-nav a", has_text=label).click()
            assert page.url.endswith(expected_hash), (width, label, page.url)
        page.locator(".pd-nav a[href='/services']").click()
        assert page.url.endswith("/services")
        assert page.locator("#airport").count() == 1
        page.goto(BASE + "/", wait_until="domcontentloaded")

        # Three approved service cards must be clickable and reach the intended target.
        page.locator('.pd-services-three a[aria-label^="Трансфер"]').click()
        assert page.url.endswith("#quick-order"), page.url
        for name, anchor_id in [("Доставка посылок", "parcel"), ("Персональный водитель", "driver")]:
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.locator('.pd-services-three a[aria-label^="' + name + '"]').click()
            assert page.url.endswith("/services#" + anchor_id), (name, page.url)
            assert page.locator("#" + anchor_id).count() == 1
        page.goto(BASE + "/", wait_until="domcontentloaded")

        # Four fare cards must prefill the actual quick form with correct routing.
        for place in ["Аэропорт Вильнюса (VNO)", "Каунас", "Клайпеда", "Варшава"]:
            page.locator('.pd-destinations a.fare-link[data-to="' + place + '"]').click()
            assert page.url.endswith("#quick-order"), (width, place, page.url)
            assert page.locator("#quick-from").input_value() == "Вильнюс", place
            assert page.locator("#quick-to").input_value() == place, place
        print(f"MOBILE_NAV_OK width={width} nav=4 service_cards=3 fare_cards=4", flush=True)
        page.locator('a.fare-link[data-to="Каунас"]').click()
        assert page.locator("#quick-from").input_value() == "Вильнюс"
        assert page.locator("#quick-to").input_value() == "Каунас"
        page.locator("#quick-date").fill("2026-12-04")
        page.locator("#quick-time").fill("14:30")
        # QA order API is stubbed: never submit real orders from visual test.
        intercepted = []
        def synthetic_booking(route):
            intercepted.append(route.request.post_data_json)
            route.fulfill(status=201, content_type="application/json",
                          body='{"qa_only":true,"trip":{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}')
        page.route("**/preview/api/qa-booking", synthetic_booking)
        page.locator('#quick-trip-form button').click()
        page.locator("#quick-order-status").get_by_text("Тестовая заявка", exact=False).wait_for()
        assert intercepted[-1]["source"] == "quick"
        assert intercepted[-1]["from"] == "Вильнюс"
        assert intercepted[-1]["to"] == "Каунас"
        assert page.locator("#route-details").get_attribute("open") is None
        assert page.locator("#quick-date").input_value() == "2026-12-04"
        page.unroute("**/preview/api/qa-booking")
        page.locator("header a[href='/services']").click()
        assert page.url.endswith("/services")
        assert page.locator("#jumpstart").count() == 1
        assert page.locator("#sober").count() == 1
        # New quick-booking flow must remain on the approved design and must
        # NOT reopen the old map. All test submissions are browser-intercepted.
        page.goto(BASE + "/", wait_until="domcontentloaded")
        posted = []
        def synthetic_booking(route):
            posted.append(route.request.post_data_json)
            route.fulfill(status=201, content_type="application/json",
                          body='{"qa_only":true,"trip":{"id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}')
        page.route("**/preview/api/qa-booking", synthetic_booking)
        assert not page.locator("#quick-trip-form").evaluate("(form) => form.checkValidity()")
        assert page.locator("#route-details").get_attribute("open") is None
        for destination, date_value, time_value in [
            ("Аэропорт Вильнюса (VNO)", "2026-12-04", "07:15"),
            ("Каунас", "2026-12-05", "14:30"),
            ("Клайпеда", "2026-12-06", "20:45"),
            ("Варшава", "2026-12-07", "05:40")
        ]:
            page.locator('.pd-destinations .fare-link[data-to="' + destination + '"]').click()
            assert page.locator("#quick-from").input_value() == "Вильнюс"
            assert page.locator("#quick-to").input_value() == destination
            page.locator("#quick-date").fill(date_value)
            page.locator("#quick-time").fill(time_value)
            page.locator('#quick-trip-form button[type="submit"]').click()
            page.locator("#quick-order-status").get_by_text("Тестовая заявка", exact=False).wait_for()
            assert posted[-1]["to"] == destination
            assert posted[-1]["source"] == "quick"
            assert page.locator("#route-details").get_attribute("open") is None
        assert len(posted) == 4
        print(f"QUICK_BOOKING_OK width={width} routes=4 dates=4 times=4 no_legacy_map=true mocked_posts=4", flush=True)
        page.unroute("**/preview/api/qa-booking")
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.screenshot(path=f"mobile-qa-screenshots/home-{width}.png", full_page=True)
        print(f"MOBILE_QA_OK width={width} images=8 services=3 fares=4 no_overflow=true quick_booking=true services_page=true", flush=True)
        page.close()
    browser.close()
