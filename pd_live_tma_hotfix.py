"""Minimal production TMA cache hotfix. Never deploys a stale GitHub template.

Requires a recent independently verified pd_safe_backup snapshot. This tool
does not restart the web app, access API secrets, or change orders/payments.
Run without --apply to preview and validate all source code before writing.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from pd_safe_backup import verify_backup


PROBE = '''"""Public fingerprint of active PRIVATE DRIVE files; contains no personal data."""
from hashlib import sha256
from pathlib import Path
from flask import jsonify
_ROOT = Path(__file__).resolve().parent
def register(app):
    @app.get('/api/release')
    def pd_release_fingerprint():
        filenames=('miniapp/templates/index.html','miniapp_server.py','pd_tips_widget.js')
        digest=sha256()
        for filename in filenames:
            digest.update(sha256((_ROOT/filename).read_bytes()).digest())
        r=jsonify(status='ok',release=digest.hexdigest()[:16])
        r.headers['Cache-Control']='no-store, max-age=0'
        return r
'''

CSS = re.compile(r'css=\x27<link rel="stylesheet" href="/assets/pd-contact-icons\.css\?v=[^"\x27<>]+">\x27')
JS = re.compile(r'scripts\+=\x27<script src="/assets/pd-tips-widget\.js\?v=[^"\x27<>]+"></script>\x27')
GUARD = re.compile(r'if \x27src="/assets/pd-tips-widget\.js\?v=[^"\x27<>]+"\x27 not in html:')
ROOT_DEFAULT = '/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform_widget(text):
    if 'def asset_version(' in text and "asset_version('pd_tips_widget.js')" in text:
        return text  # Already using content-addressed assets.
    if text.count('from pathlib import Path') != 1:
        raise RuntimeError('Unexpected widget imports; refusing live edit')
    text=text.replace('from pathlib import Path', 'from pathlib import Path\nfrom hashlib import sha256', 1)
    if text.count('def register(app):') != 1:
        raise RuntimeError('Unexpected widget structure; refusing live edit')
    text=text.replace('def register(app):', '''def asset_version(name):
    return sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()[:16]

def register(app):''', 1)
    old="response.headers['Cache-Control']='public, max-age=300'"
    if text.count(old)!=2:
        raise RuntimeError('Unexpected cache header count; refusing live edit')
    text=text.replace(old,"response.headers['Cache-Control']='no-store, max-age=0'")
    for pattern, replacement in (
        (CSS, '''css='<link rel="stylesheet" href="/assets/pd-contact-icons.css?v='+asset_version('pd_contact_icons.css')+'">\x27'''),
        (JS, '''scripts+='<script src="/assets/pd-tips-widget.js?v='+asset_version('pd_tips_widget.js')+'"></script>\x27'''),
        (GUARD, '''if 'src="/assets/pd-tips-widget.js?' not in html:'''),
    ):
        text,count=pattern.subn(lambda _m: replacement,text)
        if count!=1:
            raise RuntimeError('Unknown live asset template; refusing edit: '+pattern.pattern)
    ast.parse(text)
    if '20261028-tips-entry-v3' in text or 'max-age=300' in text:
        raise RuntimeError('Old version unexpectedly remains')
    return text


def transform_server(text):
    if 'pd_release_fingerprint' in text or 'pd_release_probe.register(app)' in text:
        return text
    needle='import pd_tips_widget\npd_tips_widget.register(app)'
    if text.count(needle)!=1:
        raise RuntimeError('Could not safely locate existing widget registration')
    text=text.replace(needle,needle+'\n\nimport pd_release_probe\npd_release_probe.register(app)',1)
    ast.parse(text)
    return text


def prepare(root, snapshot):
    manifest=json.loads((snapshot/'MANIFEST.json').read_text(encoding='utf-8'))
    count=verify_backup(snapshot)
    if count < 7 or any(name not in manifest['files'] for name in ('orders.db','users.db','miniapp_server.py','pd_tips_widget.py','miniapp/templates/index.html')):
        raise RuntimeError('Full code + database backup is missing')
    patches={}
    for name,func in (('pd_tips_widget.py',transform_widget),('miniapp_server.py',transform_server)):
        live=root/name
        original=live.read_bytes()
        if sha(original)!=manifest['files'][name]['sha256']:
            raise RuntimeError('Live file differs from verified backup: '+name)
        new=func(original.decode('utf-8')).encode('utf-8')
        patches[name]=new
    if not (root/'pd_release_probe.py').exists():
        ast.parse(PROBE)
        patches['pd_release_probe.py']=PROBE.encode('utf-8')
    else:
        # Never overwrite a custom or newly deployed endpoint.
        existing=(root/'pd_release_probe.py').read_text(encoding='utf-8')
        if 'def register(app)' not in existing or "@app.get('/api/release')" not in existing:
            raise RuntimeError('Existing release probe differs; stop')
    return patches


def apply(root, patches):
    tempfiles=[]
    originals={}
    changed=[]
    try:
        for name,contents in patches.items():
            target=root/name
            originals[name]=target.read_bytes() if target.exists() else None
            if originals[name]==contents:
                continue
            with tempfile.NamedTemporaryFile(dir=str(target.parent),prefix='.pd_hotfix_',delete=False) as handle:
                handle.write(contents)
                tmp=Path(handle.name)
            os.chmod(tmp,0o600)
            tempfiles.append((tmp,target,name))
        for tmp,target,name in tempfiles:
            os.replace(tmp,target)
            changed.append(name)
    except Exception:
        # Roll back only the files written in this attempt.
        for name in reversed(changed):
            target=root/name
            if originals[name] is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(originals[name])
        raise
    return changed


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path(ROOT_DEFAULT))
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    root=args.root.resolve()
    snapshot=args.snapshot.resolve()
    patches=prepare(root,snapshot)
    print('HOTFIX_PREFLIGHT_OK',len(patches),'files')
    print('NEW_RELEASE_HASHES',[(name,sha(contents)[:16]) for name,contents in patches.items()])
    if not args.apply:
        print('DRY_RUN_ONLY, production unchanged')
        return
    print('HOTFIX_APPLIED',apply(root,patches))
    print('MANUAL_WEB_RELOAD_REQUIRED; do not reload unless site owner authorizes deployment')


if __name__=='__main__':
    main()
