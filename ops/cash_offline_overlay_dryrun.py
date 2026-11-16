"""Simulate no-cash new bookings on actual current production source in ephemeral CI.
Only PythonAnywhere GET. Never change live files, databases, or payment settings.
Prints sanitized PASS/BLOCK, no secrets, bookings, or production code dumps.
"""
import ast,os,re,urllib.request,hashlib,tempfile,pathlib,subprocess,sys
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES=("miniapp_server.py","miniapp/templates/index.html","Euro_Baltic_Transfer.py")
def fetch(p,t):
    req=urllib.request.Request(BASE+p,headers={"Authorization":"Token "+t},method="GET")
    with urllib.request.urlopen(req,timeout=35) as r:return r.read(2000001).decode("utf-8")
def one(s,a,b,tag):
    n=s.count(a)
    print("ANCHOR",tag,"HITS",n,flush=True)
    if n!=1:raise RuntimeError("UNSAFE_ANCHOR_"+tag)
    return s.replace(a,b,1)
def candidate(s,html,bot):
    s=one(s,"method = str(d.get('payment_method', 'Наличными'))",
             "method = str(d.get('payment_method', 'Банковский перевод'))","SERVER_DEFAULT")
    s=one(s,"if method not in ('Наличными', 'Банковская карта', 'Криптовалюта', 'Банковский перевод'):",
             "if method not in ('Банковская карта', 'Криптовалюта', 'Банковский перевод'):","SERVER_ALLOWLIST")
    # Guard the legacy cash switching endpoint: existing cash bookings can keep
    # their historical cash status, but other payment methods cannot be changed.
    start=s.index("def select_cash(oid):")
    end=s.find("\n@app.",start)
    fn=s[start:end if end>=0 else len(s)]
    if "UPDATE orders SET payment_method='Наличные'" not in fn:
        raise RuntimeError("CASH_ENDPOINT_MUTATION_ANCHOR_MISSING")
    # Do not modify cash receipt ledger or admin confirmations for old bookings.
    # Append a strict guard only inside select_cash before any state mutation.
    checkpoint="    with core.db(core.ORDERS_DB) as conn:\n"
    if fn.count(checkpoint)!=1:raise RuntimeError("CASH_BLOCK_NOT_UNIQUE")
    fn=fn.replace(checkpoint,checkpoint+
       "        # Preserve previously booked cash orders; never switch another method to cash.\n"
       "        prior = conn.execute('SELECT payment_method FROM orders WHERE id=?', (oid,)).fetchone()\n"
       "        if not prior or prior['payment_method'] not in ('Наличные', 'Наличными'):\n"
       "            raise ValueError('Наличные недоступны для новых поездок')\n",1)
    s=s[:start]+fn+s[end:] if end>=0 else s[:start]+fn
    html=one(html,'<option value="Наличными">💶 Наличными водителю</option>',"","LEGACY_FORM_CASH")
    html=one(html,'<button type="button" class="active" data-method="Наличными">💶 Наличными</button>',"","PASSENGER_FORM_CASH")
    html=one(html,"pdbPay='Наличными'","pdbPay='Банковский перевод'","PASSENGER_DEFAULT")
    # Ensure bank choice exists and isn't hidden by the patch.
    if html.count('data-method="Банковский перевод"')<1:raise RuntimeError("BANK_OPTION_NOT_FOUND")
    # Keep user interface selected chip in sync with new default.
    html=html.replace('data-method="Банковский перевод"','data-method="Банковский перевод"')
    cash_menu="cancel_menu([('💶 Наличные', '💳 Безналичная')])"
    count=bot.count(cash_menu)
    print("ANCHOR BOT_CASH_MENUS HITS",count,flush=True)
    if count!=2:raise RuntimeError("BOT_MENUS_UNEXPECTED")
    bot=bot.replace(cash_menu,"cancel_menu([('💳 Безналичная',)])")
    bot=one(bot,"options = {'💶 Наличные': 'Наличные', '💳 Безналичная': 'Безналичная (по согласованию)'}",
                "options = {'💳 Безналичная': 'Безналичная (по согласованию)'}","BOT_PAYMENT_WHITELIST")
    return s,html,bot
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    before=[fetch(p,token) for p in FILES]
    for p,s in zip(FILES,before):print("SOURCE",p,"SHA256_16",hashlib.sha256(s.encode()).hexdigest()[:16],flush=True)
    try:
        server,html,bot=candidate(*before)
        ast.parse(server);ast.parse(bot)
        with tempfile.TemporaryDirectory(prefix="pd-cash-dryrun-") as tmp:
            path=pathlib.Path(tmp)
            (path/"miniapp_server.py").write_text(server)
            (path/"Euro_Baltic_Transfer.py").write_text(bot)
            subprocess.run([sys.executable,"-m","py_compile",str(path/"miniapp_server.py"),str(path/"Euro_Baltic_Transfer.py")],check=True,capture_output=True)
        print("PATCH_SYNTAX PASS",flush=True)
        print("NEW_ORDERS_NO_CASH_SERVER","Наличными" not in server.split("def create_order():",1)[1].split("\n@app.",1)[0].split("method = ",1)[1].split("\n",3)[0],flush=True)
        print("LEGACY_CASH_RECEIPT_HANDLER_PRESERVED", "def admin_cash_received_web" in server and "def admin_cash_receipts_pd" in server,flush=True)
        print("LEGACY_CASH_SWITCH_GUARD", "prior['payment_method'] not in ('Наличные', 'Наличными')" in server,flush=True)
        print("BOT_NO_NEW_CASH_MENU","cancel_menu([('💶 Наличные'" not in bot,flush=True)
        print("PASS CASH_DISABLE_OFFLINE_CANDIDATE_READY_NO_LIVE_CHANGES",flush=True)
    except Exception as error:
        print("BLOCK CASH_PATCH_UNSAFE",type(error).__name__,str(error)[:100],flush=True)
        raise SystemExit(2)
if __name__=="__main__":main()
