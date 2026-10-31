"""Isolated public asset and Telegram SDK initialization regression checks."""
import unittest
from flask import Flask
from pd_tips_widget import register, asset_version
from pd_release_probe import register as register_release, fingerprint


class TelegramMiniAppAssetTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.add_url_rule('/', endpoint='home', view_func=lambda: '<html><head></head><body><main>PRIVATE DRIVE</main></body></html>')
        register(app)
        register_release(app)
        self.client = app.test_client()

    def test_versioned_assets_not_cached(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('https://telegram.org/js/telegram-web-app.js'), 1)
        self.assertEqual(html.count('/assets/pd-tips-widget.js?v='), 1)
        self.assertIn('/assets/pd-tips-widget.js?v='+asset_version('pd_tips_widget.js'), html)
        self.assertIn('/assets/pd-contact-icons.css?v='+asset_version('pd_contact_icons.css'), html)
        for path in ['/assets/pd-tips-widget.js', '/assets/pd-contact-icons.css']:
            resource = self.client.get(path)
            self.assertEqual(resource.status_code, 200)
            self.assertIn('no-store', resource.headers.get('Cache-Control',''))

    def test_public_release_fingerprint_is_current_and_uncached(self):
        response = self.client.get('/api/release')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json.get('release'), fingerprint())
        self.assertEqual(len(response.json.get('release','')), 16)
        self.assertIn('no-store', response.headers.get('Cache-Control',''))
        self.assertNotIn('token', str(response.json).lower())

    def test_telegram_sdk_initialized_once_in_booking_template(self):
        from pathlib import Path
        template = (Path(__file__).resolve().parent / 'miniapp' / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(template.count('src="https://telegram.org/js/telegram-web-app.js"'), 1)
        self.assertIn('const tg=window.Telegram?.WebApp;', template)
        self.assertIn('tg?.ready();tg?.expand()', template)
        self.assertIn('X-Telegram-Init-Data', template)
        self.assertIn("cache:'no-store'", template)


if __name__ == '__main__':
    unittest.main()
