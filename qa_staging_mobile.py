"""Responsive browser check for the isolated PRIVATE DRIVE staging homepage."""
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
import time

URL = "http://127.0.0.1:8765/"
for _ in range(40):
    try:
        with urlopen(URL, timeout=1) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(0.5)
else:
    raise AssertionError("Local staging server not available")

Path("mobile-qa-screenshots").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for width, height in [(320, 720), (390, 844), (768, 1024), (1280, 850)]:
        page = browser.new_page(viewport={"width":width,"height":height}, device_scale_factor=1)
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        page.route("https://unpkg.com/**", lambda route: route.abort())
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.locator(".hero-stage").scroll_into_view_if_needed()
        info = page.evaluate("""() => {
           const ids = ['pd-user-logo-4-original.webp','pd-user-photo-6-original.webp','pd-user-photo-7-original.webp','pd-approved-mock1-hero.webp'];
           const pics = ids.map(id => [...document.querySelectorAll('img')].find(x=>x.src.includes(id)));
           const hero = document.querySelector('.hero');
           const gallery = document.querySelector('.hero-stage');
           return {viewport:innerWidth, pageWidth:document.documentElement.scrollWidth,
              images:pics.map((img,i)=>({found:!!img,loaded:!!img && img.complete && img.naturalWidth>=(i===3?420:864)})),
              galleryWidth:gallery?.getBoundingClientRect().width||0,
              heroWidth:hero?.getBoundingClientRect().width||0,
              booking:!!document.querySelector('#passenger-preview'),
              map:!!document.querySelector('#order-live-map')};
        }""")
        assert info["pageWidth"] <= width+2, f"Horizontal overflow {width}: {info}"
        assert all(i["loaded"] for i in info["images"]), f"Image loading failed {width}: {info}"
        assert info["galleryWidth"] > 120, f"Gallery clipped {width}: {info}"
        assert info["booking"] and info["map"], f"Existing functionality missing {width}: {info}"
        page.screenshot(path=f"mobile-qa-screenshots/home-{width}.png", full_page=True)
        print(f"MOBILE_QA_OK width={width} no_overflow=true photos_loaded=4 booking_and_map_present=true",flush=True)
        page.close()
    browser.close()
