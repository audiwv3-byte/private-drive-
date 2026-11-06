"""Stable-file backup via official PythonAnywhere Files API.
Refuses when SQLite WAL/journal exists or DB changes across two reads.
Never logs content, sends data to GitHub artifacts, or touches live source.
"""
import os, json, hashlib, sqlite3, sys, time, secrets, tempfile
from pathlib import Path
import requests
BASE='https://www.pythonanywhere.com/api/v0/user/wilsonpark'
ROOT='/home/wilsonpark/dating_lithuania_bot/'
EXPECTED='de35369744f830ba8ab9215a7f3a800d34a5e6f992b2cd23dcf3a87df1e1caca'
def digest(x):return hashlib.sha256(x).hexdigest()
def main():
    token=os.environ['PA_API_TOKEN'].strip()
    if token.lower().startswith('token '):token=token[6:].strip()
    token=''.join(token.split())
    s=requests.Session();s.headers.update({'Authorization':'Token '+token})
    if s.get(BASE+'/cpu/',timeout=25).status_code!=200:raise RuntimeError('API auth failed')
    def get(path):
        r=s.get(BASE+'/files/path'+path,timeout=35)
        if r.status_code!=200:raise RuntimeError('Missing file '+Path(path).name)
        return r.content
    source=get(ROOT+'bot.py')
    if digest(source)!=EXPECTED:raise RuntimeError('Live code mismatch')
    for ext in ('-wal','-shm','-journal'):
        r=s.head(BASE+'/files/path'+ROOT+'dating.sqlite3'+ext,timeout=25)
        if r.status_code==200:raise RuntimeError('SQLite sidecar exists; raw backup forbidden')
        if r.status_code!=404:raise RuntimeError('Cannot validate SQLite sidecar')
    first=get(ROOT+'dating.sqlite3')
    time.sleep(2)
    second=get(ROOT+'dating.sqlite3')
    if first!=second or len(first)<4096:raise RuntimeError('Database changed during double-read')
    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td)/'snapshot.sqlite3';tmp.write_bytes(second)
        with sqlite3.connect(tmp.as_uri()+'?mode=ro',uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Database corrupt')
            tables=sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            if 'profiles' not in tables:raise RuntimeError('Unexpected DB schema')
            count=db.execute('SELECT count(*) FROM profiles').fetchone()[0]
    snap='/home/wilsonpark/dating_lithuania_safe_backups/api_stable_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+secrets.token_hex(4)+'/'
    def upload(name,b):
        path=snap+name
        probe=s.get(BASE+'/files/path'+path,timeout=25)
        if probe.status_code!=404:raise RuntimeError('Cannot create unique backup path')
        r=s.post(BASE+'/files/path'+path,files={'content':(name,b,'application/octet-stream')},timeout=35)
        if r.status_code not in (200,201):raise RuntimeError('Backup upload HTTP '+str(r.status_code))
        if digest(get(path))!=digest(b):raise RuntimeError('Backup verification failure')
    upload('bot.py',source)
    upload('dating.sqlite3',second)
    manifest={'file_hashes':{'bot.py':digest(source),'dating.sqlite3':digest(second)},'mode':'stable_raw_copy','source_untouched':True,'integrity':'ok','tables':tables,'profiles_count':count}
    upload('MANIFEST.json',json.dumps(manifest,ensure_ascii=False).encode())
    third=get(ROOT+'dating.sqlite3')
    if digest(third)!=digest(second):print('BACKUP_WARNING live data advanced after snapshot',flush=True)
    print('BACKUP_VERIFIED',snap,flush=True)
    print('SCHEMA_TABLES',','.join(tables),flush=True)
    print('PROFILES_COUNT',count,flush=True)
    print('INTEGRITY_OK',flush=True)
if __name__=='__main__':main()
