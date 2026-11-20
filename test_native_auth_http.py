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


    def test_email_identity_reuses_id_without_granting_admin(self):
        from pd_native_auth_roles import get_role, bootstrap_owner
        db = sqlite3.connect(":memory:")
        delivered = []
        now = [2000]
        app = make_native_auth_app(db,
            b"test-secret-long-enough-32-characters-123",
            lambda channel, dest, code: delivered.append((channel, dest, code)),
            lambda: now[0])

        def request(path, payload):
            body = json.dumps(payload).encode()
            statuses = []
            data = b"".join(app({
                "REQUEST_METHOD": "POST", "PATH_INFO": path,
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": io.BytesIO(body), "REMOTE_ADDR": "127.0.0.1",
            }, lambda status, headers: statuses.append(status)))
            return int(statuses[0][:3]), json.loads(data)

        status, challenge = request("/native-auth/request-code",
            {"channel": "email", "destination": "ACCOUNT@EXAMPLE.COM",
             "role": "admin", "telegram_id": "7035610182"})
        self.assertEqual(status, 202)
        self.assertNotIn("code", challenge)
        self.assertEqual(delivered[0][:2], ("email", "ACCOUNT@EXAMPLE.COM"))
        status, result = request("/native-auth/verify-code",
            {"challenge_id": challenge["challenge_id"],
             "code": delivered[-1][2], "role": "admin"})
        self.assertEqual(status, 200)
        self.assertEqual(result["role"], "passenger")
        self.assertEqual(get_role(db, result["user_id"]), "passenger")
        self.assertNotIn("telegram_id", result)
        with self.assertRaises(PermissionError):
            bootstrap_owner(db, result["user_id"],
                supplied_secret="a-long-private-test-bootstrap-secret",
                configured_secret="a-long-private-test-bootstrap-secret",
                now=2000)

        now[0] += 61
        status, challenge2 = request("/native-auth/request-code",
            {"channel": "email", "destination": "account@example.com"})
        self.assertEqual(status, 202)
        status, result2 = request("/native-auth/verify-code",
            {"challenge_id": challenge2["challenge_id"],
             "code": delivered[-1][2]})
        self.assertEqual(status, 200)
        self.assertEqual(result["user_id"], result2["user_id"])
        self.assertEqual(result2["role"], "passenger")
        self.assertEqual(request("/native-auth/verify-code",
            {"challenge_id": challenge2["challenge_id"],
             "code": delivered[-1][2]})[0], 401)


if __name__ == "__main__":
    unittest.main()
