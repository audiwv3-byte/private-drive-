import io
import json
import sqlite3
import unittest
from pd_native_auth_http import make_native_auth_app

class HttpTests(unittest.TestCase):
    def test_flow(self):
        sent = []
        app = make_native_auth_app(sqlite3.connect(":memory:"), b"test-secret-long-enough-32-characters-123", lambda a,b,c:sent.append(c), lambda:1000)
        def request(path, payload):
            body = json.dumps(payload).encode()
            result = []
            data = b"".join(app({"REQUEST_METHOD":"POST","PATH_INFO":path,"CONTENT_TYPE":"application/json","CONTENT_LENGTH":str(len(body)),"wsgi.input":io.BytesIO(body),"REMOTE_ADDR":"127.0.0.1"}, lambda status,headers:result.append(status)))
            return result[0],json.loads(data)
        status, response = request("/native-auth/request-code",{"channel":"email","destination":"test@example.com"})
        self.assertTrue(status.startswith("202"))
        self.assertNotIn("code",response)
        status, verified = request("/native-auth/verify-code",{"challenge_id":response["challenge_id"],"code":sent[0]})
        self.assertTrue(status.startswith("200"))
        self.assertTrue(verified["verified"])
        status, _ = request("/native-auth/verify-code",{"challenge_id":response["challenge_id"],"code":sent[0]})
        self.assertTrue(status.startswith("401"))

if __name__ == "__main__":
    unittest.main()
