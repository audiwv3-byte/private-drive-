import io
import sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone
from flask import Flask,request,jsonify
from PIL import Image
import pd_onboarding

def test_document_acl(tmp_path):
    class Core:
        USERS_DB=tmp_path/'isolated.sqlite'
        @staticmethod
        @contextmanager
        def db(path):
            conn=sqlite3.connect(path)
            conn.row_factory=sqlite3.Row
            try:
                with conn: yield conn
            finally: conn.close()
        @staticmethod
        def is_admin(uid): return uid==201
        @staticmethod
        def now(): return datetime.now(timezone.utc)
    app=Flask(__name__)
    @app.get('/api/me')
    def me(): return jsonify(ok=True)
    @app.errorhandler(PermissionError)
    def denied(e): return jsonify(error='denied'),403
    def auth():
        if request.headers.get('X-QA-User') not in ('101','102','201'): raise PermissionError()
        return int(request.headers['X-QA-User']),{}
    pd_onboarding.register(app,Core,auth)
    output=io.BytesIO()
    Image.new('RGB',(1200,800),'blue').save(output,'JPEG')
    with Core.db(Core.USERS_DB) as db:
        db.execute("INSERT INTO pd_driver_documents VALUES (101,'license_front',?,'2026-01-01')",(output.getvalue(),))
    client=app.test_client()
    path='/api/driver/documents/101/license_front'
    for uid,status in ((None,403),('102',403),('101',200),('201',200)):
        response=client.get(path,headers={'X-QA-User':uid} if uid else {})
        assert response.status_code==status
        assert response.headers['Cache-Control']=='private, no-store'
        if status==200: assert response.mimetype=='image/jpeg'
        else: assert response.mimetype=='application/json'
    for uid,status in (('102',403),('201',200)):
        response=client.get('/api/admin/driver-applications',headers={'X-QA-User':uid})
        assert response.status_code==status and response.headers['Cache-Control']=='private, no-store'
    with app.test_request_context('/api/driver/application',method='POST',data={'license_front':(io.BytesIO(output.getvalue()),'test.jpg')}):
        clean=pd_onboarding.read_photos()['license_front']
        with Image.open(io.BytesIO(clean)) as img:
            assert not img.getexif() and img.format=='JPEG'
    print('PASS document owner/admin ACL, denial, no-store and image sanitization')
