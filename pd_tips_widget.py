"""Public page widgets and shared contact icons."""
from pathlib import Path
from flask import request, Response
PAGES={'/','/privacy','/legal','/driver-privacy','/payment-terms'}
def register(app):
    @app.get('/assets/pd-tips-widget.js')
    def pd_tips_widget_script():
        response=Response(Path(__file__).with_suffix('.js').read_text(),mimetype='application/javascript')
        response.headers['Cache-Control']='public, max-age=300'
        return response
    @app.get('/assets/pd-contact-icons.css')
    def pd_contact_icons_style():
        response=Response(Path(__file__).with_name('pd_contact_icons.css').read_text(),mimetype='text/css')
        response.headers['Cache-Control']='public, max-age=300'
        return response
    @app.after_request
    def pd_global_tips(response):
        if request.method!='GET' or request.path not in PAGES or response.status_code!=200 or response.mimetype!='text/html':
            return response
        html=response.get_data(as_text=True)
        if 'pd-contact-icons.css' not in html:
            css='<link rel="stylesheet" href="/assets/pd-contact-icons.css?v=20261028">'
            html=html.replace('</head>',css+'</head>') if '</head>' in html else css+html
        if 'src="/assets/pd-tips-widget.js?v=20261028-tips-entry-v2"' not in html:
            scripts=''
            if 'telegram-web-app.js' not in html:
                scripts+='<script src="https://telegram.org/js/telegram-web-app.js"></script>'
            scripts+='<script src="/assets/pd-tips-widget.js?v=20261028-tips-entry-v2"></script>'
            html=html.replace('</body>',scripts+'</body>') if '</body>' in html else html+scripts
        response.set_data(html)
        return response
