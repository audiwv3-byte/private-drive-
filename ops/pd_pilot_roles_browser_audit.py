"""Production PRIVATE DRIVE pilot audit: anonymous browser navigation only.

Safety: all non-GET requests blocked. No Telegram credentials/initData,
no booking submissions, payment calls, order mutations, or DB changes.
Server-side authenticated role flows are separately tested in isolated CI.
"""
from playwright.sync_api import sync_playwright
from urllib.parse import urlparse

BASE="https://wilsonpark.pythonanywhere.com/"
PROTECTED=("/api/order","/api/admin/","/api/payment/","/api/trip/","/api/pilot","/api/driver")
EXPECTED=("pdObLanguage","pdObRole","pdbOrigin","pdbDest","pdbDate","pdbTime",
          "pdbPays","pdbAgree","pdRoleBar")
def run(browser,device):
    mobile=device=="mobile"
    context=browser.new_context(viewport={"width":390 if mobile else 1300,
                                          "height":844 if mobile else 900},
         is_mobile=mobile,has_touch=mobile,locale="ru-RU",
         permissions=[])
    page=context.new_page()
    blocked=[]
    pageerrors=[]
    page.on("pageerror",lambda e:pageerrors.append(type(e).__name__))
    def guard(route):
        request=route.request
        path=urlparse(request.url).path
        if request.method.upper()!="GET" or any(path.startswith(prefix) for prefix in PROTECTED):
            blocked.append((request.method,path.split("/")[1] if "/" in path else ""))
            route.abort("blockedbyclient")
        else:
            route.continue_()
    page.route("**/*",guard)
    response=page.goto(BASE,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(1100)
    assert response and response.status==200,"PUBLIC_PAGE_FAILURE"
    missing=[selector for selector in EXPECTED if page.locator("#"+selector).count()!=1]
    assert not missing,("MISSING_UI_CONTROLS",missing)
    funcs=("pdWelcomeSelect","pdWelcomeContinue","pdApplyRoleAccess",
           "pdbSendOrder","pdEnterPilot","pdSwitchTab","pdOpenLiveTripV4")
    present={name:page.evaluate("(name)=>typeof window[name]==='function'",name) for name in funcs}
    # The trip runtime may be a separately loaded JS module, so report absence without
    # claiming a live GPS test if the function is not present.
    assert all(present[k] for k in ("pdWelcomeSelect","pdbSendOrder","pdEnterPilot","pdSwitchTab")), "CORE_JS_HANDLER_MISSING"
    # A browser without Telegram credentials must never display operational admin tools.
    anon=page.evaluate("""()=>{
      const ids=['pdRoleBar','adminNav','pdPilotBack'];
      return Object.fromEntries(ids.map(id=>{
        const el=document.getElementById(id);
        return [id,el?!!(el.hidden||el.classList.contains('hidden')||getComputedStyle(el).display==='none'):true];
      }))
    }""")
    assert anon["pdRoleBar"],"ANONYMOUS_ADMIN_ROLE_BAR_VISIBLE"
    assert anon["adminNav"],"ANONYMOUS_ADMIN_NAV_VISIBLE"
    assert anon["pdPilotBack"],"ANONYMOUS_PILOT_BACK_VISIBLE"
    # Static inspection of passenger controls (no data entry or request).
    booking=page.evaluate("""()=>{
      const ids=['pdbOrigin','pdbDest','pdbDate','pdbTime','pdbPays','pdbAgree'];
      return ids.every(id=>document.getElementById(id)!==null)
    }""")
    assert booking,"PASSENGER_BOOKING_CONTROLS_MISSING"
    # No write requests can escape the network guard.
    print("DEVICE",device,"PUBLIC_HTTP_200 OK",flush=True)
    print("DEVICE",device,"PASSENGER_BOOKING_FIELDS OK",flush=True)
    print("DEVICE",device,"UNAUTH_ADMIN_PILOT_CONTROLS_HIDDEN OK",flush=True)
    print("DEVICE",device,"HANDLERS",sum(present.values()),"OF",len(funcs),flush=True)
    print("DEVICE",device,"JS_PAGE_ERRORS",len(pageerrors),flush=True)
    print("DEVICE",device,"GUARDED_REQUESTS_BLOCKED",len(blocked),flush=True)
    assert not pageerrors,("PAGE_SCRIPT_ERRORS",len(pageerrors))
    context.close()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    run(browser,"mobile")
    run(browser,"desktop")
    browser.close()
print("PILOT_READONLY_BROWSER_GATE_PASSED",flush=True)
print("AUTHENTICATED_PILOT_DISPATCHER_E2E_NOT_TESTED_WITHOUT_TELEGRAM_SESSION",flush=True)
