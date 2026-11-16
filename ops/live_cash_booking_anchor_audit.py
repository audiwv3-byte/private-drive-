"""Inspect only cash booking route/UI anchors in live production sources.
PythonAnywhere GET-only. No personal data, env, SQLite or payment API calls.
"""
import os,re,urllib.request
ROOT="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
F={"SERVER":"miniapp_server.py","UI":"miniapp/templates/index.html","BOT":"Euro_Baltic_Transfer.py","BANK":"pd_bank_transfer.py"}
def read(f,t):
    with urllib.request.urlopen(urllib.request.Request(ROOT+f,method="GET",headers={"Authorization":"Token "+t}),timeout=35) as r:return r.read(2000001).decode("utf-8")
def print_near(label,code,patterns,limit=12):
    lines=code.splitlines()
    found=[]
    for i,s in enumerate(lines):
        if any(re.search(p,s,re.I) for p in patterns):found.append(i)
    print("SECTION",label,"MATCHES",len(found),flush=True)
    used=set()
    for i in found[:limit]:
        for j in range(max(0,i-1),min(len(lines),i+2)):
            if j in used:continue
            used.add(j)
            s=lines[j]
            if re.search(r"(secret|token|API_KEY|password|authorization|PAYPAL_CLIENT|STRIPE_SECRET)",s,re.I):continue
            print("LINE",j+1,s[:200],flush=True)
def main():
    tok=os.environ["PYTHONANYWHERE_API_TOKEN"].strip().removeprefix("Token ")
    d={k:read(p,tok) for k,p in F.items()}
    print_near("SERVER_NEW_BOOKING",d["SERVER"],[r"payment_method\s*=",r"def submit_order",r"def create_order",r"@app.post\('/api/order",r"Наличн"],16)
    print_near("SERVER_LEGACY_CASH",d["SERVER"],[r"@app.post\('/api/payment/<int:oid>/cash",r"def cash_",r"def admin_cash",r"def payment_"],14)
    print_near("UI_NEW_BOOKING",d["UI"],[r"id=[\"']payMethod",r"id=[\"']pdbPays",r"pdbPay\s*=",r"cashNotice\(",r"payment_method"],17)
    print_near("BOT_NEW_BOOKING",d["BOT"],[r"Наличн",r"payment_method",r"select_cash"],14)
    print_near("BANK_CASH_COMPAT",d["BANK"],[r"select_cash",r"Ожидается оплата наличными"],8)
    print("NO_WRITES_NO_ORDERS_NO_PAYMENTS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:print("ERROR",type(e).__name__,flush=True);raise SystemExit(1)
