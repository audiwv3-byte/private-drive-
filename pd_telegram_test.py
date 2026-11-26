"""Verify Telegram Mini App data on the isolated dispatcher without a bot token."""

import base64
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.parse import parse_qsl

# Telegram's Ed25519 production public key, encoded as SubjectPublicKeyInfo DER.
# The test refers to a staging website; participants still use production Telegram.
PUBLIC_KEY = bytes.fromhex(
    "302a300506032b6570032100e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
)
VALID_ID = re.compile(r"[1-9][0-9]{0,15}")


def verify_init_data(raw, bot_id, tester_id):
    if not 0 < len(raw) <= 8192:
        raise PermissionError("unauthorized")
    try:
        pairs = parse_qsl(raw, strict_parsing=True, max_num_fields=32, errors="strict")
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("Duplicate fields")
        date = fields["auth_date"]
        signature = fields.pop("signature")
        fields.pop("hash", None)
        if not re.fullmatch(r"[0-9]{1,12}", date) or not re.fullmatch(r"[A-Za-z0-9_-]{86}(?:==)?", signature):
            raise ValueError("Invalid signature fields")
        age = int(time.time()) - int(date)
        if not -30 <= age <= 900:
            raise ValueError("Expired")
        user_id = json.loads(fields["user"])["id"]
        if type(user_id) is not int:
            raise ValueError("Invalid user")
        message = (bot_id + ":WebAppData\n" + "\n".join(
            f"{key}={value}" for key, value in sorted(fields.items())
        )).encode()
        signature_bytes = base64.urlsafe_b64decode(signature.rstrip("=") + "==")
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise PermissionError("unauthorized") from None
    with TemporaryDirectory(prefix="pd-telegram-proof-") as directory:
        root = Path(directory)
        key_file = root / "key.der"
        message_file = root / "message"
        signature_file = root / "signature"
        key_file.write_bytes(PUBLIC_KEY)
        message_file.write_bytes(message)
        signature_file.write_bytes(signature_bytes)
        result = subprocess.run([
            "openssl", "pkeyutl", "-verify", "-pubin", "-keyform", "DER",
            "-inkey", str(key_file), "-rawin", "-in", str(message_file),
            "-sigfile", str(signature_file),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False)
    if result.returncode:
        raise PermissionError("unauthorized")
    if str(user_id) != tester_id:
        raise PermissionError("forbidden")
