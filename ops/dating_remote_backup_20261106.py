"""One-shot server-local SQLite backup, no writes to the live app."""
import json, hashlib, sqlite3, sys, time
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path('/home/wilsonpark/dating_lithuania_bot')
BKP=Path('/home/wilsonpark/dating_lithuania_safe_backups')
OPS=Path('/home/wilsonpark/dating_safe_ops_20261106')
EXPECTED='de35369744f830ba8ab9215a7f3a800d34a5e6f992b2cd23dcf3a87df1e1caca'
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def safe_dir(p):
    p.mkdir(parents=True,exist_ok=True,mode=0o700)
    p.chmod(0o700)
    return p
def check(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
        raise RuntimeError('SQLite integrity check failed')
def run(nonce):
    if not ROOT.is_dir() or ROOT.is_symlink():raise RuntimeError('Live folder is unavailable')
    code=ROOT/'bot.py'; cfg=ROOT/'settings.json'; srcdb=ROOT/'dating.sqlite3'
    if digest(code)!=EXPECTED:raise RuntimeError('Production source hash has changed, stopped')
    if not cfg.is_file() or not srcdb.is_file():raise RuntimeError('Missing production files')
    if code.is_symlink() or cfg.is_symlink() or srcdb.is_symlink():raise RuntimeError('Unexpected symbolic link')
    folder=safe_dir(safe_dir(BKP)/('snapshot_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+nonce))
    hashes={}
    for file in (code,cfg):
        dest=folder/file.name
        dest.write_bytes(file.read_bytes());dest.chmod(0o600)
        if digest(file)!=digest(dest):raise RuntimeError('Code/config backup hash mismatch')
        hashes[file.name]=digest(dest)
    with sqlite3.connect(srcdb.as_uri()+'?mode=ro',uri=True,timeout=30) as original:
        check(original)
        with sqlite3.connect(folder/'dating.sqlite3',timeout=30) as dest:
            original.backup(dest,pages=32,sleep=0.1)
    (folder/'dating.sqlite3').chmod(0o600)
    with sqlite3.connect(folder/'dating.sqlite3') as snap:
        check(snap)
        tables=sorted(x[0] for x in snap.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        if 'profiles' not in tables:raise RuntimeError('profiles table not present')
        count=snap.execute('SELECT count(*) FROM profiles').fetchone()[0]
    hashes['dating.sqlite3']=digest(folder/'dating.sqlite3')
    manifest={'date_utc':datetime.now(timezone.utc).isoformat(),'source_hash':EXPECTED,'files_sha256':hashes,'tables':tables,'profiles':count,'verified':True}
    (folder/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
    (folder/'MANIFEST.json').chmod(0o600)
    return {'result':'PASS','backup':str(folder),'db_integrity':'PASS','source_unchanged':True,'profiles':count,'tables':tables,'manifest_sha256':digest(folder/'MANIFEST.json')}
def main():
    nonce=sys.argv[1] if len(sys.argv)>1 else ''
    if len(nonce)!=12 or not nonce.isalnum():raise SystemExit('Invalid nonce')
    safe_dir(OPS)
    try:status=run(nonce)
    except Exception as exc:status={'result':'FAIL','error_type':type(exc).__name__,'reason':str(exc)[:120]}
    out=OPS/('status_'+nonce+'.json')
    out.write_text(json.dumps(status),encoding='utf-8');out.chmod(0o600)
    time.sleep(150)
if __name__=='__main__':main()
