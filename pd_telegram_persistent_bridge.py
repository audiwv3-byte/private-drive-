"""Opt-in staging-only Telegram order delivery. No payment or messaging calls."""
import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.error

def enabled():
    return (os.getenv("PD_DISPATCH_STAGING_ONLY") == "1"
            and os.getenv("PD_PAYMENT_MODE") == "disabled"
            and os.getenv("PD_TELEGRAM_PERSISTENT_BRIDGE") == "1")

class DeliveryError(RuntimeError):
    pass

def deliver(order, *, transport=None, sleep=time.sleep, clock=time.time):
    if not enabled():
        raise DeliveryError("bridge_disabled")
    key = os.getenv("PD_DISPATCH_ORDERS_INGEST_SECRET", "")
    url = os.getenv("PD_TELEGRAM_DISPATCH_IMPORT_URL", "")
    if len(key) < 32 or url != "https://private-drive-dispatcher-staging.onrender.com/v1/dispatch/orders/import":
        raise DeliveryError("bridge_configuration")
    payload = {"source":"telegram_miniapp","source_order_id":str(order["id"]),
               "from":order["origin"],"to":order["destination"],
               "trip_date":order["trip_date"],"trip_time":order["trip_time"]}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",",":")).encode()
    if transport is None:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        transport = urllib.request.build_opener(NoRedirect()).open
    for attempt in range(3):
        issued = str(int(clock()))
        signature = hmac.new(key.encode(), issued.encode()+b"."+raw, hashlib.sha256).hexdigest()
        req = urllib.request.Request(url, data=raw, headers={"Content-Type":"application/json",
            "X-PD-Order-Timestamp":issued,"X-PD-Order-Signature":signature}, method="POST")
        try:
            with transport(req, timeout=4) as response:
                result = json.loads(response.read(8192))
                if response.status in (200,201) and result.get("order_id") and result.get("payment_mode") == "disabled":
                    return result
                raise DeliveryError("invalid_acknowledgement")
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504):
                raise DeliveryError("import_rejected") from None
        except (OSError, ValueError):
            pass
        if attempt < 2:
            sleep(2**attempt)
    raise DeliveryError("delivery_unavailable")
