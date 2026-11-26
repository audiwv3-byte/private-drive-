"""Run the actual Dart iOS QA API client through a strictly local HTTP fixture.
The logical endpoint is HTTPS qa.invalid; only the injected test transport
maps it to localhost. No physical iOS sensor or real TLS handshake is claimed.
"""
import os, subprocess, json
from pathlib import Path

def run(oid, body, finish=False):
    args=["flutter","test","test/qa31_ios_real_api_test.dart","--reporter","expanded",
          "--dart-define=PD_INTERNAL_QA=true","--dart-define=PD_QA28_GPS=true",
          "--dart-define=PD_QA_IOS_GPS=true", "--dart-define=QA31_ORDER="+oid,
          "--dart-define=QA31_BODY="+json.dumps(body,separators=(",",":")),
          "--dart-define=QA31_FINISH="+str(finish).lower()]
    subprocess.run(args,cwd=Path(__file__).resolve().parents[2]/"flutter_app",check=True,timeout=90)

def publish_fix(oid, fix):
    # Timestamp generated in Dart, but preserve fixture timestamp for DB assertion.
    import time
    fix["captured_at"]=int(time.time())
    run(oid,fix)

def finish_bridge(oid):
    run(oid,{},True)
