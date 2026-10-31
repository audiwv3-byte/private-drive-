"""Public page widgets and shared contact icons."""
from pathlib import Path
from hashlib import sha256
import os
from urllib.parse import urlsplit
from flask import request, Response
PAGES={'/','/privacy','/legal','/driver-privacy','/payment-terms'}

def asset_version(name):
    # Content-addressed URL makes Telegram's embedded WebView fetch each new release.
    return sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()[:16]
def register(app):
    @app.get('/assets/pd-tips-widget.js')
    def pd_tips_widget_script():
        response=Response(Path(__file__).with_suffix('.js').read_text(),mimetype='application/javascript')
        response.headers['Cache-Control']='no-store, max-age=0'
        return response
    @app.get('/assets/pd-contact-icons.css')
    def pd_contact_icons_style():
        response=Response(Path(__file__).with_name('pd_contact_icons.css').read_text(),mimetype='text/css')
        response.headers['Cache-Control']='public, max-age=300'
        return response
    @app.after_request
    def pd_add_paypal_tips_option(response):
        """Expose only a verified PayPal URL, never internal configuration or tokens."""
        if request.method != 'GET' or request.path != '/api/tips/options' or not response.is_json or response.status_code != 200:
            return response
        configured = os.getenv('PD_PAYPAL_TIPS_URL', '').strip()
        if not configured:
            return response
        try:
            url = urlsplit(configured)
            if (url.scheme != 'https' or url.username or url.password or url.port not in (None, 443)
                    or url.hostname not in ('paypal.me', 'www.paypal.com', 'paypal.com')
                    or not url.path or url.path == '/'):
                return response
        except ValueError:
            return response
        data = response.get_json(silent=True)
        if isinstance(data, dict):
            data['paypal_url'] = configured
            response.set_data(app.json.dumps(data))
        return response
    @app.after_request
    def pd_global_tips(response):
        if request.method!='GET' or request.path not in PAGES or response.status_code!=200 or response.mimetype!='text/html':
            return response
        html=response.get_data(as_text=True)
        if 'pd-contact-icons.css' not in html:
            css='<link rel="stylesheet" href="/assets/pd-contact-icons.css?v='+asset_version('pd_contact_icons.css')+'">'
            html=html.replace('</head>',css+'</head>') if '</head>' in html else css+html
        if 'src="/assets/pd-tips-widget.js?' not in html:
            scripts=''
            if 'telegram-web-app.js' not in html:
                scripts+='<script src="https://telegram.org/js/telegram-web-app.js"></script>'
            scripts+='<script src="/assets/pd-tips-widget.js?v='+asset_version('pd_tips_widget.js')+'"></script>'
            html=html.replace('</body>',scripts+'</body>') if '</body>' in html else html+scripts
        response.set_data(html)
        return response
