"""GET-only PRIVATE DRIVE PayPal live integration compatibility audit.

Only reads source text from PythonAnywhere. Prints structural booleans,
source hashes, and safe compatibility statuses. Never reads .env or databases.
Never calls PayPal. Never writes production source.
"""
import ast
import hashlib
import os
import re
import urllib.error
import urllib.request

API = "https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT = "/home/wilsonpark/euro_baltic_transfer"
LIVE = ROOT + "/PRIVATE_DRIVE_MiniApp_2026_10_18"
FILES = ("miniapp_server.py", "miniapp/templates/index.html", "pd_paypal_checkout.py")
BASE = "https://raw.githubusercontent.com/audiwv3-byte/private-drive-/caba0b9dd005e13b11f76e8f11788a4599db4926/pd_paypal_checkout.py"

def get(url, token=None):
    hdr = {"Authorization": "Token " + token} if token else {}
    req = urllib.request.Request(url, headers=hdr, method="GET")
    with urllib.request.urlopen(req, timeout=35) as res:
        return res.read(2_000_001).decode("utf-8")

def check(code, label):
    try:
        ast.parse(code)
        print(label + "_SYNTAX OK", flush=True)
        return True
    except SyntaxError:
        print(label + "_SYNTAX INVALID", flush=True)
        return False

def main():
    token = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    token = re.sub(r"^Token\s+", "", token, flags=re.I)
    if not token:
        raise ValueError("API credential not configured")
    print("MODE READ_ONLY_GET_NO_SECRETS_NO_PAYMENTS", flush=True)
    live = {}
    for filename in FILES:
        try:
            content = get(API + LIVE + "/" + filename, token)
        except urllib.error.HTTPError as e:
            print("FILE", filename, "HTTP", e.code, flush=True)
            raise ValueError("Required file inaccessible") from None
        if not 0 < len(content) <= 2000000:
            raise ValueError("File size outside expected limits")
        live[filename] = content
        print("FILE", filename, "PRESENT", len(content),
              hashlib.sha256(content.encode()).hexdigest()[:16], flush=True)
    server = live[FILES[0]]
    template = live[FILES[1]]
    module = live[FILES[2]]
    check(server, "SERVER")
    check(module, "PAYPAL")
    reference = get(BASE)
    print("PAYPAL_MODULE_MATCHES_REVIEWED_PR", module == reference, flush=True)
    checks = {
        "paypal_not_yet_integrated": "import pd_paypal_checkout" not in server
            and "/paypal/create" not in server and "/paypal/capture" not in server,
        "server_import_anchor": server.count("import pd_fixed_prices") == 1,
        "server_stripe_anchor": server.count("# Stripe: the secret key is loaded") == 1,
        "server_payment_route": server.count("@app.get('/api/payment/<int:oid>')") == 1,
        "payment_json_anchor": server.count("card_link=") >= 1,
        "html_payment_ui": "async function openPay(" in template and "async function cashNotice(" in template,
        "html_cryptonotice": "cryptoNotice(" in template,
        "html_new_booking": 'id="pdbPays"' in template,
        "no_existing_paypal": "paypalNotice(" not in template and "/paypal/create" not in template,
        "staging_mode_does_not_activate": "PD_PAYPAL_MODE" not in server,
    }
    for key, val in checks.items():
        print("COMPAT", key, "OK" if val else "REVIEW_REQUIRED", flush=True)
    # Code under review is an integration proposal, not authorized for live use.
    print("DEPLOYMENT_BLOCKED_DEFAULT", flush=True)
    if all(checks.values()) and module == reference:
        print("STAGING_OVERLAY_PRECONDITIONS_OK", flush=True)
    else:
        print("STAGING_OVERLAY_REQUIRES_REVIEW", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AUDIT_FAILED", type(e).__name__, flush=True)
        raise SystemExit(1)
