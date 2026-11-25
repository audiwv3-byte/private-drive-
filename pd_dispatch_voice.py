"""Opt-in audio calls for authenticated members of an isolated QA trip."""

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from threading import Lock
import time
from urllib.parse import urlsplit
import uuid

from test_sync_server.pd_demo_server import TripError


@dataclass
class Call:
    id: str
    caller: str
    members: tuple
    expires: float
    accepted: bool = False
    last_seen: dict = field(default_factory=dict)


class StagingVoiceCalls:
    def __init__(self, store, url, key, secret):
        self.store = store
        self.url = url
        self.key = key
        self.secret = secret
        self.lock = Lock()
        self.calls = {}

    @classmethod
    def from_environment(cls, store):
        if os.environ.get("PD_DISPATCH_STAGING_ONLY") != "1":
            return None
        url = os.environ.get("PD_QA_LIVEKIT_URL", "")
        key = os.environ.get("PD_QA_LIVEKIT_KEY", "")
        secret = os.environ.get("PD_QA_LIVEKIT_SECRET", "")
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "wss" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or not key
                    or not secret):
                return None
        except ValueError:
            return None
        return cls(store, url, key, secret)

    def _token(self, call, role):
        now = int(time.time())

        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b"=")

        payload = {
            "iss": self.key, "sub": f"{call.id}-{role}", "nbf": now - 5,
            "exp": now + 60,
            "video": {
                "room": call.id, "roomJoin": True, "canSubscribe": True,
                "canPublish": True, "canPublishSources": ["microphone"],
                "canPublishData": False,
            },
        }
        unsigned = b".".join(encode(json.dumps(part, separators=(",", ":")).encode())
                            for part in ({"alg": "HS256", "typ": "JWT"}, payload))
        signature = hmac.new(self.secret.encode(), unsigned, hashlib.sha256).digest()
        return (unsigned + b"." + encode(signature)).decode("ascii")

    def handle(self, trip_id, role, actor, data=None):
        if role not in ("pilot", "passenger"):
            raise TripError("forbidden", 403)
        with self.lock:
            trip = self.store.get(trip_id, role, actor)
            if not trip["pilot"] or trip["status"] not in ("assigned", "approaching", "underway"):
                raise TripError("call_unavailable", 409)
            now = time.monotonic()
            self.calls = {
                key: value for key, value in self.calls.items()
                if value.expires > now and (
                    not value.accepted or min(value.last_seen.values()) + 30 > now
                )
            }
            members = (trip["owner"], trip["pilot"])
            call = self.calls.get(trip_id)
            if call and call.members != members:
                del self.calls[trip_id]
                call = None
            if call and call.accepted:
                call.last_seen[role] = now
            if data is not None:
                action = data.get("action")
                if action == "invite":
                    if not call:
                        call = Call(uuid.uuid4().hex, role, members, now + 40)
                        self.calls[trip_id] = call
                elif not call or data.get("id") != call.id:
                    raise TripError("call_expired", 409)
                elif action == "accept" and call.caller != role and not call.accepted:
                    call.accepted = True
                    call.expires = now + 3600
                    call.last_seen = {"pilot": now, "passenger": now}
                elif action == "end":
                    del self.calls[trip_id]
                    call = None
                elif action == "join" and call.accepted:
                    return {"url": self.url, "token": self._token(call, role)}
                else:
                    raise TripError("invalid_call_action", 409)
            if not call:
                return {"call": None}
            return {"call": {
                "id": call.id, "caller": call.caller,
                "state": "accepted" if call.accepted else "ringing",
            }}
