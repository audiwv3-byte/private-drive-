"""Regression tests for safe surgical changes to live PythonAnywhere sources."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from pd_live_tma_hotfix import transform_widget,transform_server,prepare,apply
from pd_safe_backup import make_backup

ORIGINAL_WIDGET = '''from pathlib import Path
from flask import Response
PAGES={'/'}
def register(app):
    def javascript():
        response=Response(Path(__file__).with_suffix('.js').read_text())
        response.headers['Cache-Control']='public, max-age=300'
        return response
    def css_file():
        response=Response(Path(__file__).with_name('pd_contact_icons.css').read_text())
        response.headers['Cache-Control']='public, max-age=300'
        return response
    def pd_global_tips(response):
        html=response.get_data(as_text=True)
        if 'pd-contact-icons.css' not in html:
            css='<link rel="stylesheet" href="/assets/pd-contact-icons.css?v=20261028">'
            html=html.replace('</head>',css+'</head>')
        if 'src="/assets/pd-tips-widget.js?v=20261028-tips-entry-v3"' not in html:
            scripts=''
            scripts+='<script src="/assets/pd-tips-widget.js?v=20261028-tips-entry-v3"></script>'
            html=html.replace('</body>',scripts+'</body>')
        return response
'''
ORIGINAL_SERVER = '''from flask import Flask
app=Flask(__name__)
import pd_tips_widget
pd_tips_widget.register(app)
'''

class SafeProductionHotfixTests(unittest.TestCase):
    def test_original_widget_transformed_without_overwriting_other_code(self):
        changed=transform_widget(ORIGINAL_WIDGET)
        self.assertIn("asset_version('pd_tips_widget.js')",changed)
        self.assertIn("asset_version('pd_contact_icons.css')",changed)
        self.assertNotIn('20261028',changed)
        self.assertEqual(changed.count("no-store, max-age=0"),2)
        self.assertIn('def pd_global_tips',changed)
        self.assertEqual(transform_widget(changed),changed)
        self.assertIn('pd_release_probe.register(app)',transform_server(ORIGINAL_SERVER))

    def test_stop_on_unrecognized_live_code(self):
        with self.assertRaises(RuntimeError):
            transform_widget(ORIGINAL_WIDGET.replace('20261028-tips-entry-v3','otherversion',1))
        with self.assertRaises(RuntimeError):
            transform_server("app=Flask(__name__)")

    def test_only_after_verified_backup_then_apply(self):
        with tempfile.TemporaryDirectory() as dirname:
            base=Path(dirname)
            root=base/'live'
            root.mkdir()
            files={
                'miniapp_server.py':ORIGINAL_SERVER,
                'pd_tips_widget.py':ORIGINAL_WIDGET,
                'pd_tips_widget.js':"console.log('SAFE_TEST');"+' '*60,
                'pd_contact_icons.css':'div { color: black; }'+' '*60,
                'Euro_Baltic_Transfer.py':'# TEST BOT'+(' '*60),
                'miniapp/templates/index.html':'<html><body>TEST PAGE</body></html>'+' '*60
            }
            for name,content in files.items():
                path=root/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(content)
            for name in ('orders.db','users.db'):
                with sqlite3.connect(root/name) as db:
                    db.execute('CREATE TABLE t (x integer)')
                    db.execute('INSERT INTO t VALUES (1)')
            snapshot=make_backup(root,base/'private_backups')
            patches=prepare(root,snapshot)
            self.assertEqual(set(patches),{'miniapp_server.py','pd_tips_widget.py','pd_release_probe.py'})
            self.assertEqual((root/'pd_tips_widget.py').read_text(),ORIGINAL_WIDGET)
            changed=apply(root,patches)
            self.assertEqual(len(changed),3)
            self.assertTrue((root/'pd_release_probe.py').exists())
            self.assertIn("asset_version('pd_tips_widget.js')",(root/'pd_tips_widget.py').read_text())
            # A modified live source never passes the original snapshot's checksum gate.
            with self.assertRaises(RuntimeError):
                prepare(root,snapshot)

if __name__=='__main__':
    unittest.main()
