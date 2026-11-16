"""PR27 pilot cockpit overlay against LIVE HTML in ephemeral CI — GET only.

Verifies anchored insertion after existing runtime/pilot/admin scripts, preserved
passenger/dispatcher markup, preserved payment endpoints, exact current SHA.
No writes, bookings, user data, production changes, or real GPS.
"""
import hashlib,os,pathlib,re,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
LIVE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
HTML="miniapp/templates/index.html"
PINNED="402cf5244b74325285122aa87604b4ba700df9072a5389d55f527243bd99796d"
MODULE=ROOT/"experimental/pd_pilot_cockpit_staged.js"
ADAPTER=ROOT/"experimental/pd_pilot_cockpit_adapter_staged.js"
CSS=ROOT/"experimental/pd_pilot_cockpit_staged.css"
def validate(condition,label):
    if not condition:raise RuntimeError("BLOCK_"+label)
    print("PASS",label,flush=True)
def overlay(src):
    module=MODULE.read_text(encoding="utf8")
    adapter=ADAPTER.read_text(encoding="utf8")
    css=CSS.read_text(encoding="utf8")
    for fragment in ("</script","</style","<!--"):
        validate(fragment not in module.lower() and fragment not in adapter.lower() and fragment not in css.lower(),"SAFE_INLINE_PAYLOAD")
    validate(src.count("</body>")==1 and src.count("</head>")==1,"UNIQUE_HTML_INSERTION_ANCHORS")
    scripts=("/assets/pd-trip-runtime-v4.js","/assets/pd-pilot-cabinet-v4.js","/assets/pd-admin-console-v4.js")
    indexes=[src.find("/assets/"+v.split("/assets/")[-1]) for v in scripts]
    validate(all(x>=0 for x in indexes) and indexes==sorted(indexes),"KNOWN_SCRIPT_LOAD_ORDER")
    validate(src.count('id="pdPilotWork"')==1 and src.count('id="pdPilotWorkList"')==1,"PILOT_HOST_UNIQUE")
    validate('pdPilotCockpit' not in src,"NO_EXISTING_COCKPIT")
    # CSS is scoped to the cockpit body class. No other UI is touched.
    out=src.replace("</head>","<style id=\"pd-pilot-cockpit-stage-css\">\\n"+css+"\\n</style>\\n</head>",1)
    embed=("<script id=\"pd-pilot-cockpit-stage-js\">\\n"+module+"\\n</script>\\n"+
           "<script id=\"pd-pilot-cockpit-adapter-stage-js\">\\n"+adapter+"\\n</script>\\n")
    out=out.replace("</body>",embed+"</body>",1)
    validate(out.count("pd-pilot-cockpit-stage-css")==1 and out.count("pd-pilot-cockpit-adapter-stage-js")==1,"EXACTLY_ONCE_INJECTED")
    for text in ('id="pdbPays"','id="pdPilotWork"','id="pdPilotWorkList"','id="mainNav"',
                 "/assets/pd-admin-console-v4.js","/assets/pd-trip-runtime-v4.js"):
        validate(src.count(text)==out.count(text),"EXISTING_UI_UNCHANGED_"+text[:38])
    validate(out.endswith("</html>\\n") or out.rstrip().endswith("</html>"),"VALID_HTML_TAIL")
    return out
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    request=urllib.request.Request(API+LIVE+HTML,method="GET",headers={"Authorization":"Token "+token})
    with urllib.request.urlopen(request,timeout=40) as r:src=r.read(600000).decode("utf8")
    actual=hashlib.sha256(src.encode()).hexdigest()
    print("SOURCE_SHA256",actual,flush=True)
    validate(actual==PINNED,"EXACT_LIVE_HTML_HASH_MATCH")
    out=overlay(src)
    print("CANDIDATE_SHA256",hashlib.sha256(out.encode()).hexdigest(),flush=True)
    print("CANDIDATE_BYTES",len(out.encode()),flush=True)
    for path in (MODULE,ADAPTER):
        subprocess.run(["node","--check",str(path)],capture_output=True,check=True)
    print("PASS MODULE_AND_ADAPTER_NODE_SYNTAX",flush=True)
    with tempfile.TemporaryDirectory(prefix="pd-cockpit-html-offline-") as tmp:
        dest=pathlib.Path(tmp)/"index.html"
        dest.write_text(out,encoding="utf8")
        validate(dest.read_text(encoding="utf8")==out,"TEMPORARY_OVERLAY_READBACK")
    print("PILOT_LIVE_OVERLAY_DRYRUN_PASS",flush=True)
    print("NO_PYTHONANYWHERE_WRITES_NO_ORDERS_NO_PAYMENTS_NO_GPS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("PILOT_DRYRUN_BLOCKED",type(e).__name__,str(e)[:100],flush=True)
        raise SystemExit(1)
