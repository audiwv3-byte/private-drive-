"""Exercise signed tips access and the bot entry without sending messages."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit, parse_qs

source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='pd-tips-test-') as temporary:
    root = Path(temporary)
    for path in source.glob('*.py'):
        shutil.copy2(path, root / path.name)
    shutil.copytree(source / 'miniapp', root / 'miniapp')
    (root / 'pd_translations.json').write_text('{}')
    os.environ.update(BOT_TOKEN='123:TEST_TIPS_ONLY', ADMIN_IDS='999',
                      PD_PAYMENT_MODE='disabled', ORS_API_KEY='')
    sys.path.insert(0, str(root))
    import miniapp_server as server
    core = server.core
    core.initialize()
    client = server.app.test_client()
    assert client.get('/api/tips/options').status_code == 401
    data = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': 101, 'first_name': 'Test'})}
    secret = hmac.new(b'WebAppData', core.TOKEN.encode(), hashlib.sha256).digest()
    data['hash'] = hmac.new(secret, '\n'.join(f'{key}={value}' for key, value in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    response = client.get('/api/tips/options', headers={'X-Telegram-Init-Data': urlencode(data)})
    assert response.status_code == 200
    assert response.json['reference'] == 'TIP-PD-101'
    assert core.user_record(101) is None, 'Tips must not require passenger registration'
    sent = []
    core.say = lambda *args, **kwargs: sent.append(args)
    core.start(SimpleNamespace(text='/start tips', chat=SimpleNamespace(id=101, type='private'), from_user=SimpleNamespace(id=101)))
    assert len(sent) == 1
    button = sent[0][2].keyboard[0][0]
    assert parse_qs(urlsplit(button.web_app.url).query)['start'] == ['tips']
    assert core.user_record(101) is None
    assert core.state_get(101) is None
    print('PASS: signed tips without registration; guest authentication retained; /start tips launches the tips Mini App')
