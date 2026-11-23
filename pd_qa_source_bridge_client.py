"""Explicit opt-in test-only sender contract for Telegram QA orders.

This module is intentionally not imported by the live Telegram bot or Mini App.
Never forward real contacts, Telegram IDs, chats, payments, or customer records.
The staging Render endpoint refuses submissions without a separate shared secret.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

STAGING_HOST = "private-drive-dispatcher-staging.onrender.com"


def signed_qa_request(order: dict, secret: str, *, timestamp: int | None = None) -> Request:
    """Build (do not send) a strictly staging-bound HMAC-authenticated request."""
    if len(secret) < 32:
        raise ValueError("A dedicated staging-only secret of at least 32 characters is required")
    if set(order) != {"source", "source_order_id", "from", "to", "trip_date", "trip_time"}:
        raise ValueError("Unexpected fields in synthetic QA order")
    if order["source"] not in ("telegram_miniapp", "telegram_bot"):
        raise ValueError("Invalid order source")
    if not isinstance(order["source_order_id"], str) or not order["source_order_id"].isdigit():
        raise ValueError("Invalid source order ID")
    if not all(isinstance(order[key], str) for key in ("from", "to", "trip_date", "trip_time")):
        raise ValueError("Synthetic QA fields must be strings")
    raw = json.dumps(order, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 8192:
        raise ValueError("QA order too large")
    ts = str(timestamp if timestamp is not None else int(time.time()))
    mac = hmac.new(secret.encode("utf-8"), ts.encode("ascii") + b"." + raw,
                   hashlib.sha256).hexdigest()
    url = "https://" + STAGING_HOST + "/v1/qa-source/import"
    return Request(url, data=raw, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-PD-QA-Timestamp": ts,
        "X-PD-QA-Signature": mac,
    })


def send_synthetic_qa_order(order: dict) -> dict:
    """Only callable with deliberate opt-in; never used in production entry points."""
    if os.environ.get("PD_QA_SOURCE_BRIDGE_SEND_ENABLED") != "1":
        raise RuntimeError("Sending disabled unless manually enabled for isolated QA")
    secret = os.environ.get("PD_QA_SOURCE_BRIDGE_SECRET", "")
    req = signed_qa_request(order, secret)
    if urlparse(req.full_url).hostname != STAGING_HOST:
        raise RuntimeError("Non-staging destination refused")
    with urlopen(req, timeout=15) as response:
        body = response.read(8193)
        if len(body) > 8192:
            raise RuntimeError("Response too large")
        data = json.loads(body)
        if response.status not in (200, 201) or data.get("qa_only") is not True:
            raise RuntimeError("Staging server did not confirm QA order")
        return data
