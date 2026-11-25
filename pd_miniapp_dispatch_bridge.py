"""Staging-only server-to-server bridge for already saved Telegram Mini App orders.

Never accept a client supplied source or endpoint. The dispatcher is the sole
order queue; Telegram's local row only supplies the stable legacy order ID.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class DispatchBridgeUnavailable(Exception):
    """The local order exists, but central dispatch did not acknowledge it."""


def bridge_enabled():
    return (os.getenv("PD_MINIAPP_DISPATCH_BRIDGE") == "1"
            and os.getenv("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.getenv("PD_PAYMENT_MODE") == "disabled")


def publish_telegram_order(order, *, open_url=urlopen, now=time.time):
    """Return central order ID, or raise. No local rows are deleted or rewritten."""
    if not bridge_enabled():
        return None
    secret = os.getenv("PD_DISPATCH_ORDERS_INGEST_SECRET", "")
    endpoint = os.getenv("PD_MINIAPP_DISPATCH_IMPORT_URL", "")
    url = urlsplit(endpoint)
    if (len(secret) < 32 or url.scheme != "https" or not url.hostname
            or url.username or url.password or url.port not in (None, 443)
            or url.path != "/v1/dispatch/orders/import" or url.query
            or url.fragment):
        raise DispatchBridgeUnavailable("bridge_not_configured")
    payload = {
        "source": "telegram_miniapp",
        "source_order_id": str(order["id"]),
        "from": str(order["origin"]),
        "to": str(order["destination"]),
        "trip_date": datetime.strptime(str(order["trip_date"]), "%d.%m.%Y").strftime("%Y-%m-%d") if "." in str(order["trip_date"]) else str(order["trip_date"]),
        "trip_time": str(order["trip_time"]),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(now()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + raw,
                         hashlib.sha256).hexdigest()
    req = Request(endpoint, data=raw, method="POST", headers={
        "Content-Type": "application/json",
        "X-PD-Order-Timestamp": timestamp,
        "X-PD-Order-Signature": signature,
    })
    try:
        with open_url(req, timeout=5) as response:
            if response.status not in (200, 201):
                raise DispatchBridgeUnavailable("dispatch_rejected")
            result = json.loads(response.read(8192))
            if (not isinstance(result, dict)
                    or result.get("source") != "telegram_miniapp"
                    or result.get("source_order_id") != str(order["id"])
                    or not result.get("order_id")
                    or result.get("payment_mode") != "disabled"):
                raise DispatchBridgeUnavailable("invalid_acknowledgement")
            return str(result["order_id"])
    except DispatchBridgeUnavailable:
        raise
    except (OSError, TimeoutError, ValueError, TypeError) as exc:
        raise DispatchBridgeUnavailable("dispatch_unavailable") from exc
