import base64
import hashlib
import io
import json
import os
import unittest

import psycopg
from PIL import Image

from pd_native_auth_postgres_http import initialize_database
from werkzeug.test import Client
from werkzeug.wrappers import Response
from pd_native_identity_http import make_identity_app, sanitize_photo, APPROVAL_TTL, PENDING_TTL


class PhotoValidationTests(unittest.TestCase):
    def test_reencode_removes_metadata(self):
        output = io.BytesIO()
        source = Image.new('RGB', (64, 64), 'blue')
        exif = Image.Exif()
        exif[270] = 'private metadata'
        source.save(output, 'JPEG', exif=exif)
        cleaned = sanitize_photo(base64.b64encode(output.getvalue()).decode())
        with Image.open(io.BytesIO(cleaned)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertFalse(image.getexif())

    def test_rejects_non_image_and_oversized_data(self):
        for data in ['bad base64', base64.b64encode(b'not an image').decode(), 'a' * 2800001]:
            with self.assertRaises((ValueError, OSError)):
                sanitize_photo(data)


@unittest.skipUnless(os.environ.get('PD_IDENTITY_TEST_DATABASE_URL'), 'isolated PostgreSQL test DB required')
class IdentityHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.environ['PD_IDENTITY_TEST_DATABASE_URL']
        initialize_database(cls.db)

    def setUp(self):
        self.now = 1800000000
        self.app = make_identity_app(lambda e, s: [], self.db, clock=lambda: self.now, start_cleanup=False)
        with psycopg.connect(self.db) as conn:
            conn.execute('TRUNCATE native_identity_checks,native_auth_sessions,native_auth_roles,native_auth_users CASCADE')
            for uid, role in [('pilot', 'pilot'), ('other', 'pilot'), ('reviewer', 'admin'), ('passenger', 'passenger')]:
                conn.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,%s)", (uid, uid, self.now))
                conn.execute('INSERT INTO native_auth_roles VALUES (%s,%s)', (uid, role))
                digest = hashlib.sha256(uid.ljust(48, 'x').encode()).hexdigest()
                conn.execute('INSERT INTO native_auth_sessions VALUES (%s,%s,%s,%s,NULL)',
                    (digest, uid, self.now, self.now + 30 * 86400))
        out = io.BytesIO()
        Image.new('RGB', (64, 64), 'blue').save(out, 'PNG')
        self.payload = {'photo': base64.b64encode(out.getvalue()).decode()}

    def request(self, uid, endpoint, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b''
        env = {'REQUEST_METHOD': 'POST' if payload is not None else 'GET',
            'PATH_INFO': '/native-identity/' + endpoint,
            'HTTP_AUTHORIZATION': 'Bearer ' + uid.ljust(48, 'x'),
            'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(body)),
            'wsgi.input': io.BytesIO(body)}
        response = []
        result = b''.join(self.app(env, lambda status, headers: response.append(status)))
        return int(response[0][:3]), json.loads(result)

    def test_submit_review_delete_and_expire_without_role_grants(self):
        code, result = self.request('pilot', 'submit', self.payload)
        self.assertEqual(code, 202)
        check_id = result['id']
        self.assertEqual(self.request('pilot', 'status')[1]['status'], 'pending')
        self.assertEqual(self.request('reviewer', 'queue')[1]['items'][0]['id'], check_id)
        self.assertEqual(self.request('reviewer', 'photo/' + check_id)[0], 200)
        self.assertEqual(self.request('reviewer', 'decision/' + check_id, {'decision': 'approved'})[0], 200)
        self.assertEqual(self.request('pilot', 'status')[1]['status'], 'approved')
        self.assertEqual(self.request('reviewer', 'photo/' + check_id)[0], 404)
        self.assertEqual(self.request('reviewer', 'decision/' + check_id, {'decision': 'approved'})[0], 409)
        with psycopg.connect(self.db) as conn:
            self.assertIsNone(conn.execute('SELECT photo FROM native_identity_checks WHERE id=%s', (check_id,)).fetchone()[0])
            self.assertEqual(conn.execute("SELECT role FROM native_auth_roles WHERE user_id='pilot'").fetchone()[0], 'pilot')
        self.now += APPROVAL_TTL
        self.assertEqual(self.request('pilot', 'status')[1]['status'], 'expired')

    def test_auth_acl_revocation_and_no_self_review(self):
        self.assertEqual(self.request('unknown', 'status')[0], 401)
        self.assertEqual(self.request('passenger', 'submit', self.payload)[0], 403)
        self.assertEqual(self.request('pilot', 'queue')[0], 403)
        check_id = self.request('reviewer', 'submit', self.payload)[1]['id']
        self.assertEqual(self.request('reviewer', 'photo/' + check_id)[0], 404)
        self.assertEqual(self.request('reviewer', 'decision/' + check_id, {'decision': 'approved'})[0], 409)
        with psycopg.connect(self.db) as conn:
            conn.execute("UPDATE native_auth_sessions SET revoked_at=%s WHERE user_id='reviewer'", (self.now,))
        self.assertEqual(self.request('reviewer', 'queue')[0], 401)

    def test_pending_retries_and_expiry(self):
        first = self.request('pilot', 'submit', self.payload)[1]
        second = self.request('pilot', 'submit', self.payload)[1]
        self.assertEqual(first['id'], second['id'])
        self.now += PENDING_TTL
        self.assertEqual(self.request('pilot', 'status')[1]['status'], 'expired')
        self.assertEqual(self.request('reviewer', 'queue')[1]['items'], [])
        with psycopg.connect(self.db) as conn:
            self.assertIsNone(conn.execute('SELECT photo FROM native_identity_checks WHERE id=%s', (first['id'],)).fetchone()[0])

    def test_future_session_and_photo_privacy(self):
        client=Client(self.app, Response)
        def get(uid,path):
            return client.get('/native-identity/'+path,headers={'Authorization':'Bearer '+uid.ljust(48,'x')})
        check_id=self.request('pilot','submit',self.payload)[1]['id']
        for uid in ('passenger','other','pilot'):
            self.assertEqual(get(uid,'photo/'+check_id).status_code,403)
        photo=get('reviewer','photo/'+check_id)
        self.assertEqual(photo.status_code,200)
        self.assertEqual(photo.headers['Cache-Control'],'no-store')
        self.assertEqual(photo.headers['X-Content-Type-Options'],'nosniff')
        with psycopg.connect(self.db) as conn:
            conn.execute("UPDATE native_auth_sessions SET created_at=%s WHERE user_id='reviewer'",(self.now+1,))
        self.assertEqual(get('reviewer','photo/'+check_id).status_code,401)
        self.assertEqual(get('reviewer','queue').status_code,401)
        self.assertEqual(self.request('reviewer','decision/'+check_id,{'decision':'approved'})[0],401)
        self.assertEqual(self.request('pilot','submit',{**self.payload,'role':'admin'})[0],400)

    def test_invalid_photo_cannot_be_submitted(self):
        self.assertEqual(self.request('pilot', 'submit', {'photo': 'invalid'})[0], 400)


if __name__ == '__main__':
    unittest.main()
