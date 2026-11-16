from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://wilsonpark.pythonanywhere.com/"
OUT = Path("passenger_previews")
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 430, "height": 932}, device_scale_factor=2,
                            is_mobile=True, has_touch=True, locale="ru-RU")
    errors=[]
    page.on("pageerror",lambda e:errors.append(str(e)[:160]))
    page.goto(URL, wait_until="domcontentloaded", timeout=50000)
    page.wait_for_timeout(2500)
    for idx in range(4):
        panel=f"step{idx}"
        present=page.locator("#"+panel).count()>0
        if not present:
            print("MISSING_PANEL",panel,flush=True)
            continue
        # Visual-only preview of the real markup; no logins, submissions,
        # API mutations or orders; does not alter server files.
        state=page.evaluate("""(panel)=>{
            document.body.classList.remove('pd-onboarding-active');
            const onboarding=document.querySelector('#pdOnboarding');
            if(onboarding)onboarding.classList.add('hidden');
            const controls=['#mainNav','.pd-language-switch','#pdRoleBar'];
            controls.forEach(sel=>document.querySelectorAll(sel).forEach(e=>e.style.display='none'));
            document.querySelectorAll('section.panel').forEach(e=>e.classList.add('hidden'));
            const target=document.getElementById(panel);
            if(!target)return null;
            target.classList.remove('hidden');
            target.style.display='block';
            window.scrollTo(0,0);
            const text=(target.innerText||'').trim().slice(0,220);
            return {heading:target.querySelector('h1,h2')?.innerText||'',text};
        }""",panel)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT/f"passenger_{idx+1:02d}.png"),full_page=True,animations="disabled")
        print("CAPTURED",idx+1,panel,state,flush=True)
    print("PAGE_ERRORS_COUNT",len(errors),flush=True)
    browser.close()
