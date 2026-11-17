"""Optional SMS delivery adapter for PRIVATE DRIVE native authentication.

Isolated from production. Sending is disabled by default. A caller must
explicitly enable delivery and inject a trusted provider transport.
Do not use the test transport in production.
"""
from pd_native_auth import normalize_destination


class SMSDeliveryDisabled(RuntimeError):
    pass


def make_sms_delivery(transport, *, enabled=False):
    """Return a callback compatible with make_native_auth_app(..., deliver=...).

    transport(to_e164, message) must be a trusted server-side implementation.
    Neither credentials nor OTPs should appear in logs.
    """
    if not callable(transport):
        raise TypeError("SMS transport must be callable")

    def deliver(channel, destination, code):
        if channel != "phone":
            raise ValueError("SMS adapter only supports phone channel")
        to = normalize_destination("phone", destination)
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError("Invalid verification code")
        if not enabled:
            raise SMSDeliveryDisabled("Real SMS delivery is disabled")
        message = f"PRIVATE DRIVE verification code: {code}. Valid for 5 minutes."
        return transport(to, message)

    return deliver
