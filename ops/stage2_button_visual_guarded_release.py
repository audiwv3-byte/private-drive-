"""One-file visual stage2 button release, opt-in only; no record mutations."""
import argparse,hashlib,os,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops import stage2_onefile_guarded_release as base
from ops.stage2_button_visual_live_dryrun import change,SOURCE_SHA,BACKEND_SHA
LIVE=base.LIVE
BACKEND=LIVE.replace("miniapp/templates/index.html","pd_onboarding.py")
TARGET_SHA="d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0"
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("--execute",action="store_true")
 args=parser.parse_args()
 if not args.execute:
  print("STAGE2_VISUAL_RELEASE_DRYRUN_DEFAULT",flush=True);return
 if os.getenv("PD_APPROVED_STAGE2_VISUAL")!="YES":
  raise RuntimeError("OPERATOR_APPROVAL_REQUIRED")
 token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
 source=base.get(LIVE,token)
 if sha(source)!=SOURCE_SHA:raise RuntimeError("ACTIVE_HTML_SHA_MISMATCH_ABORT")
 backend=base.get(BACKEND,token)
 if sha(backend)!=BACKEND_SHA:raise RuntimeError("BACKEND_SHA_CHANGED_ABORT")
 new=change(source.decode("utf8")).encode("utf8")
 if sha(new)!=TARGET_SHA:raise RuntimeError("EXPECTED_CANDIDATE_HASH_MISMATCH_ABORT")
 if not base.public(b"function pdStage2ApprovalHint(a,missingPhotos)"):
  raise RuntimeError("PRE_RELEASE_PAGE_CHECK_FAILED")
 status,_=base.call(base.API+"/files/path"+base.BACKUPS,token)
 if status!=200:raise RuntimeError("BACKUP_DIRECTORY_UNAVAILABLE")
 import datetime,secrets,urllib.error
 tag=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")+"_"+secrets.token_hex(5)
 original=base.BACKUPS+"stage2_button_visual_"+tag+"__original.html"
 candidate=base.BACKUPS+"stage2_button_visual_"+tag+"__candidate.html"
 for path in (original,candidate):
  try:base.get(path,token)
  except urllib.error.HTTPError as error:
   if error.code!=404:raise
  else:raise RuntimeError("BACKUP_PATH_ALREADY_EXISTS")
 base.put(original,source,token)
 base.put(candidate,new,token)
 if base.get(original,token)!=source or base.get(candidate,token)!=new:
  raise RuntimeError("PREWRITE_BACKUP_VERIFY_FAILED")
 if base.get(LIVE,token)!=source:raise RuntimeError("CONCURRENT_HTML_CHANGE")
 print("BACKUP_ORIGINAL_PATH",original,flush=True)
 print("BACKUP_CANDIDATE_PATH",candidate,flush=True)
 print("ORIGINAL_SHA256",sha(source),flush=True)
 print("CANDIDATE_SHA256",sha(new),flush=True)
 print("STAGE2_VISUAL_BACKUP_VERIFIED",flush=True)
 attempted=False
 try:
  attempted=True
  base.put(LIVE,new,token)
  base.reload(token)
  if not base.public(b"pd-stage2-approval-disabled-visual"):
   raise RuntimeError("PUBLIC_VISUAL_STYLE_NOT_VISIBLE")
  if not base.public(b"pd-approval-blocked-reason"):
   raise RuntimeError("PUBLIC_DISABLED_REASON_NOT_VISIBLE")
  if base.get(LIVE,token)!=new:raise RuntimeError("POSTRELEASE_READBACK_MISMATCH")
  if sha(base.get(BACKEND,token))!=BACKEND_SHA:raise RuntimeError("BACKEND_CHANGED_DURING_INSTALL")
  print("STAGE2_VISUAL_HTML_INSTALLED_VERIFIED",flush=True)
 except Exception:
  failures=[]
  if attempted:
   try:
    actual=base.get(LIVE,token)
    if actual!=source:
     if actual!=new and not (0<len(actual)<len(new) and new.startswith(actual)):
      failures.append("UNKNOWN_CONCURRENT_CONTENT")
     elif sha(base.get(original,token))!=SOURCE_SHA:
      failures.append("BACKUP_CHECKSUM_INVALID")
     else:base.put(LIVE,source,token)
   except Exception:failures.append("RESTORE_WRITE_FAILED")
  try:base.reload(token)
  except Exception:failures.append("RESTORE_RELOAD_FAILED")
  try:
   if base.get(LIVE,token)!=source:failures.append("RESTORED_HTML_SHA_INVALID")
   if not base.public(b"function pdStage2ApprovalHint(a,missingPhotos)"):
    failures.append("RESTORED_PUBLIC_PAGE_FAILED")
  except Exception:failures.append("RESTORE_VERIFY_FAILED")
  print("STAGE2_VISUAL_ROLLBACK_VERIFIED" if not failures else "STAGE2_VISUAL_MANUAL_RECOVERY_REQUIRED",flush=True)
  for f in failures:print("ERROR",f,flush=True)
  raise
if __name__=="__main__":
 try:main()
 except Exception as error:
  print("STAGE2_VISUAL_RELEASE_BLOCKED",type(error).__name__,str(error)[:130],flush=True)
  raise SystemExit(1)
