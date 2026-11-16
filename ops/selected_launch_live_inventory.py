"""Selected PRIVATE DRIVE launch updates: production GET-only compatibility inventory.
No orders, databases, payments, env, secrets or production writes.
Only source hashes and public code feature markers are printed.
"""
import os,re,hashlib,urllib.request,urllib.error
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES=("miniapp_server.py","pd_request_security.py","pd_paypal_checkout.py",
       "pd_trip_runtime_v4.py","pd_pilot_cabinet_v4.js","pd_trip_runtime_v4.js",
       "pd_admin_console_v4.js","pd_pilot_dispatch.py","pd_photo_review.py",
       "pd_registration.js","miniapp/templates/index.html","Euro_Baltic_Transfer.py")
def read(name,token):
    req=urllib.request.Request(BASE+name,method="GET",headers={"Authorization":"Token "+token})
    try:
        with urllib.request.urlopen(req,timeout=32) as res:
            dat=res.read(2000001)
            return res.status,dat.decode("utf-8")
    except urllib.error.HTTPError as exc:return exc.code,""
def flag(name,yes):print("FEATURE",name,"PRESENT" if yes else "NOT_DEMONSTRATED",flush=True)
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    data={}
    print("AUDIT READ_ONLY_SELECTED_8_FEATURES",flush=True)
    for path in FILES:
        status,content=read(path,token)
        print("FILE",path,"HTTP",status,"SHA256_16",hashlib.sha256(content.encode()).hexdigest()[:16] if content else "-",flush=True)
        data[path]=content
    server=data["miniapp_server.py"];html=data["miniapp/templates/index.html"]
    ui=data["pd_pilot_cabinet_v4.js"];gps=data["pd_trip_runtime_v4.js"]
    joined="\n".join(data.values())
    flag("WEB_AUTH_ALTERNATIVE_TO_TELEGRAM",bool(re.search(r"def (web_login|web_session|email_login|verify_email)|/api/web/(?:auth|login|register)",server,re.I)))
    flag("CASH_BOOKING_SERVER_REJECT",bool(re.search(r"(?:payment_method|method).{0,150}(?:Наличные|Наличными).{0,140}(?:raise|abort|error)|(?:Наличные|Наличными).{0,140}(?:raise|abort|error)",server,re.S)))
    flag("CASH_NEW_BOOKING_UI_CHOICE",bool(re.search(r"<option[^>]*>[^<]*(?:Наличн)",html,re.I)))
    flag("PILOT_FULLSCREEN_MAP_ROOT","pdPilotCockpit" in html or "pdPilotCockpit" in ui)
    flag("PILOT_GPS_WATCH","watchPosition" in gps)
    flag("PILOT_GPS_REUSE_MAP",bool(re.search(r"invalidateSize|setLatLng",gps)))
    flag("PAYPAL_MODULE",bool(data["pd_paypal_checkout.py"]))
    flag("PAYPAL_BUTTON","paypalNotice" in html or "pdPaypalSdk" in html)
    flag("PAYPAL_ROUTES",all(x in server for x in ("/paypal/create","/paypal/capture","/paypal/config")))
    flag("PAYPAL_SANDBOX_GATED","if mode == 'live':" in data["pd_paypal_checkout.py"])
    flag("STRIPE_CARD_VISIBLE",bool(re.search(r"Картой|Банковская карта|Stripe",html,re.I)))
    flag("LANGUAGE_SELECTOR",all(x in html for x in ("English","Lietuvi","Русск")))
    flag("PHOTO_REVIEW_MODULE","pd_photo_review" in joined)
    flag("PHOTO_REVIEW_QUEUE",bool(re.search(r"photo.?review|review.?photo",joined,re.I)))
    flag("TRIP_GUARD", "secure_legacy_status_route(app)" in server)
    flag("NO_STORE_SECURITY", "no-store" in server)
    flag("PREMIUM_GOLD",bool(re.search(r"gold|золот|#d4af37",html,re.I)))
    flag("PREMIUM_CROWN",bool(re.search(r"corona|crown|корон",html,re.I)))
    print("NOTE FEATURE_MARKERS_NOT_A_FUNCTIONAL_END_TO_END_TEST",flush=True)
    print("NO_PAYMENTS_NO_ORDERS_NO_PRODUCTION_CHANGES",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("AUDIT_ERROR",type(e).__name__,flush=True)
        raise SystemExit(1)
