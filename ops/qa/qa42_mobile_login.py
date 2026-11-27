"""QA-only OTP adapter for existing mobile sign-in contract. No SMS provider."""
import hmac
import secrets
import threading
import time
from pd_native_auth_postgres_http import read_json, reply

# Reserved fictional US numbers, never sent to a provider.
ACCOUNTS = {"+12025550101":"passenger", "+12025550102":"pilot", "+12025550103":"other_passenger"}

def new_codes():
    return {phone: f"{secrets.randbelow(1000000):06d}" for phone in ACCOUNTS}

class MobileLogin:
    def __init__(self, codes, tokens, clock=time.time):
        if set(codes) != set(ACCOUNTS):
            raise ValueError("Synthetic account set required")
        self.codes = dict(codes)
        self.tokens = tokens
        self.clock = clock
        self.until = clock() + 300
        self.challenges = {}
        self.lock = threading.Lock()

    def handle(self, environ, start_response):
        try:
            data = read_json(environ)
        except (ValueError, TypeError, UnicodeError):
            return reply(start_response, "400 Bad Request", {"error":"invalid_request"})
        now = self.clock()
        with self.lock:
            if environ["PATH_INFO"].endswith("/request-code"):
                phone = data.get("destination")
                if set(data) != {"channel","destination"} or data.get("channel") != "phone" or not isinstance(phone,str) or phone not in self.codes or now >= self.until:
                    return reply(start_response,"403 Forbidden",{"error":"sms_number_not_enabled"})
                if phone in self.challenges:
                    return reply(start_response,"429 Too Many Requests",{"error":"try_later"})
                challenge = secrets.token_urlsafe(32)
                self.challenges[phone] = [challenge,0]
                return reply(start_response,"202 Accepted",{"challenge_id":challenge,"expires_in":max(1,int(self.until-now)),"resend_after":300})
            cid, code = data.get("challenge_id"), data.get("code")
            if set(data) == {"challenge_id","code"} and isinstance(cid,str) and isinstance(code,str) and len(code)==6 and code.isascii() and code.isdigit() and now < self.until:
                for phone, state in self.challenges.items():
                    if hmac.compare_digest(state[0],cid) and phone in self.codes and state[1]<5:
                        state[1]+=1
                        if hmac.compare_digest(self.codes[phone],code):
                            del self.codes[phone]
                            identity=ACCOUNTS[phone]
                            role="pilot" if identity=="pilot" else "passenger"
                            return reply(start_response,"200 OK",{"verified":True,"role":role,"user_id":"qa39-"+identity,"access_token":self.tokens[identity],"token_type":"Bearer","expires_in":max(1,int(self.until-now)+3300)})
            return reply(start_response,"401 Unauthorized",{"error":"invalid_or_expired_code"})
