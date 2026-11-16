"""Automated UI launch smoke for real PRIVATE DRIVE production page, read-only.

No Telegram initData, no forms submitted, no orders created, no payments.
"""
from playwright.sync_api import sync_playwright
BASE="https://wilsonpark.pythonanywhere.com/"
IDS=("pdObLanguage","pdObRole","step0","step1","step2","step3","pdbOrigin","pdbDest","pdbDate","pdbTime","pdbPays","pdbAgree")
FUNCTIONS=("pdbSendOrder","openPay","pdWelcomeSelect")
def verify(browser,device):
    is_mobile=device=="mobile"
    context=browser.new_context(viewport={"width":390 if is_mobile else 1366,
                                          "height":844 if is_mobile else 900},
                                device_scale_factor=2 if is_mobile else 1,
                                is_mobile=is_mobile,has_touch=is_mobile,
                                locale="ru-RU")
    page=context.new_page()
    errs=[]
    page.on("pageerror",lambda e:errs.append(str(e).splitlines()[0][:90]))
    response=page.goto(BASE,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(1600)
    assert response and response.status==200,(device,"STATUS")
    missing=[i for i in IDS if page.locator("#"+i).count()!=1]
    assert not missing,(device,"MISSING_UI",missing)
    unavailable=[f for f in FUNCTIONS if page.evaluate("(name)=>typeof window[name] !== 'function'",f)]
    assert not unavailable,(device,"MISSING_HANDLER",unavailable)
    assert not errs,(device,"PAGE_JS_ERRORS",len(errs))
    # No wallet, payment authorization or user-sensitive paths are visited.
    print("DEVICE",device,"PUBLIC_PAGE_200","ELEMENTS",len(IDS),"HANDLERS",len(FUNCTIONS),"JS_ERRORS",len(errs),"OK",flush=True)
    context.close()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    for device in ("mobile","desktop"):
        verify(browser,device)
    browser.close()
print("LIVE_UI_READONLY_SMOKE_PASSED",flush=True)
