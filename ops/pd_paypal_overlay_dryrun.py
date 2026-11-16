"""PayPal sandbox integration overlay dry-run; GET-only, no production mutations."""
import ast
import os
import re
import urllib.request

API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
LIVE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
RAW="https://raw.githubusercontent.com/audiwv3-byte/private-drive-/caba0b9dd005e13b11f76e8f11788a4599db4926/"
def get(url, token=None):
    headers={"Authorization":"Token "+token} if token else {}
    req=urllib.request.Request(url,headers=headers,method="GET")
    with urllib.request.urlopen(req,timeout=35) as response:
        return response.read(2000001).decode("utf-8")
def one(source, original, replacement):
    if source.count(original)!=1:
        raise ValueError("ANCHOR_COUNT_MISMATCH")
    return source.replace(original,replacement,1)
def between(source,start,end):
    if source.count(start)!=1 or source.count(end)!=1:
        raise ValueError("PR_MARKER_MISSING")
    return source[source.index(start):source.index(end,source.index(start)+len(start))]
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    server=get(API+LIVE+"miniapp_server.py",token)
    html=get(API+LIVE+"miniapp/templates/index.html",token)
    reviewed_server=get(RAW+"miniapp_server.py")
    reviewed_html=get(RAW+"miniapp/templates/index.html")
    print("AUDIT GET_ONLY_IN_MEMORY_NO_SECRETS",flush=True)
    server=one(server,"import pd_fixed_prices\n","import pd_fixed_prices\nimport pd_paypal_checkout as pd_paypal\n")
    start=reviewed_server.index("paypal_available=bool(pd_paypal.settings())")
    end=reviewed_server.index(",\n",start)+1
    field=reviewed_server[start:end]
    if len(field)>450:raise ValueError("PAYMENT_FIELD_TOO_LONG")
    needle="card_link=r['card_payment_url'] if r['status']=='Подтверждена' else '',"
    server=one(server,needle,needle+"\n       "+field)
    block=between(reviewed_server,"# PayPal is OFF by default","# Stripe: the secret key")
    if "/paypal/capture" not in block:
        raise ValueError("REVIEWED_PAYPAL_ROUTES_MISSING")
    server=one(server,"# Stripe: the secret key",block+"# Stripe: the secret key")
    ast.parse(server)
    print("SERVER_PATCH_SYNTAX_OK",flush=True)
    ui_start=reviewed_html.index("p.paypal_available?")
    prefix=reviewed_html.rfind("$",0,ui_start)
    ui_end=reviewed_html.index("<div id=\"paymentDetail\"></div>",ui_start)
    ui_fragment=reviewed_html[prefix:ui_end]
    if len(ui_fragment)>220 or "paypalNotice()" not in ui_fragment:
        raise ValueError("REVIEWED_UI_FRAGMENT_INVALID")
    base_ui='<button class="pay-choice" onclick="cryptoNotice('+chr(36)+'{id})">₿ Криптовалютой</button>'
    print("HTML_UI_ANCHOR_COUNT",html.count(base_ui),flush=True)
    print("HTML_CASH_HANDLER_COUNT",html.count("async function cashNotice()"),flush=True)
    if html.count(base_ui)!=1:
        at=html.find("cryptoNotice(")
        print("UI_CONTEXT",repr(html[max(0,at-115):at+160]) if at>=0 else "NOT_FOUND",flush=True)
    html=one(html,base_ui,base_ui+ui_fragment)
    js=between(reviewed_html,"// PayPal is available only for a confirmed","async function cashNotice()")
    html=one(html,"async function cashNotice()",js+"async function cashNotice()")
    if html.count("async function paypalNotice()") !=1:
        raise ValueError("PAYPAL_HANDLER_COUNT")
    print("PASSENGER_UI_PATCH_OK",flush=True)
    print("SAFE_STAGING_OVERLAY_READY",flush=True)
    print("NO_LIVE_CHANGES_NO_PAYMENTS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as error:
        print("DRY_RUN_BLOCKED",type(error).__name__,str(error)[:100],flush=True)
        raise SystemExit(1)
