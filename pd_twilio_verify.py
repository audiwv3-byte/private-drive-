"""Isolated Twilio Verify adapter for PRIVATE DRIVE native authentication.

Not mounted into production. Real requests are opt-in and require environment
credentials. Twilio Verify generates the OTP; never generate or log it here.
"""
import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://verify.twilio.com/v2/Services"


class VerifyError(RuntimeError):
    """A redacted error; provider bodies and credentials are not exposed."""


def _configuration(env):
    sid = env.get("TWILIO_ACCOUNT_SID", "")
    token = env.get("TWILIO_AUTH_TOKEN", "")
    service = env.get("TWILIO_VERIFY_SERVICE_SID", "")
    if not sid.startswith("AC") or len(sid) != 34:
        raise ValueError("Invalid Twilio account SID")
    if not service.startswith("VA") or len(service) != 34:
        raise ValueError("Invalid Twilio Verify service SID")
    if not token:
        raise ValueError("Twilio Auth Token is missing")
    return sid, token, service


def _post(path, fields, *, env, transport):
    if env.get("TWILIO_VERIFY_ENABLED", "").lower() != "true":
        raise VerifyError("Twilio Verify sending is disabled")
    sid, token, service = _configuration(env)
    basic = base64.b64encode(f"{sid}:{token}".encode()).decode("ascii")
    request = Request(
        f"{BASE_URL}/{service}/{path}",
        data=urlencode(fields).encode("ascii"),
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with transport(request, timeout=10) as response:
            payload = json.load(response)
    except (HTTPError, URLError, ValueError, TimeoutError, OSError) from None:
        raise VerifyError("Twilio Verify request failed") from None
    if not isinstance(payload, dict):
        raise VerifyError("Unexpected Twilio Verify response")
    return payload


def start_verification(phone, *, env=None, transport=urlopen):
    """Ask Twilio to generate/send an SMS code; disabled unless explicitly enabled."""
    from pd_native_auth import normalize_destination
    to = normalize_destination("phone", phone)
    payload = _post("Verifications", {"To": to, "Channel": "sms"},
                    env=os.environ if env is None else env, transport=transport)
    if payload.get("status") != "pending":
        raise VerifyError("Twilio did not accept the verification")
    return {"status": "pending"}


def check_verification(phone, code, *, env=None, transport=urlopen):
    """Only check a code with Twilio. Does not create an app user/session."""
    from pd_native_auth import normalize_destination
    to = normalize_destination("phone", phone)
    if not isinstance(code, str) or len(code) < 4 or len(code) > 10 or not code.isascii() or not code.isdigit():
        raise ValueError("Invalid verification code")
    payload = _post("VerificationCheck", {"To": to, "Code": code},
                    env=os.environ if env is None else env, transport=transport)
    return payload.get("status") == "approved"
