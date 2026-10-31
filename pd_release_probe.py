"""Public, non-sensitive release fingerprint for PRIVATE DRIVE deployment verification.

Shows file revisions only. No API keys, personal data, DB contents, paths or
configuration values are exposed.
"""
from hashlib import sha256
from pathlib import Path
from flask import jsonify

ROOT = Path(__file__).resolve().parent
TRACKED = (
    "miniapp/templates/index.html",
    "miniapp_server.py",
    "pd_tips_widget.js",
)

def fingerprint():
    values = []
    for name in TRACKED:
        path = ROOT / name
        values.append(sha256(path.read_bytes()).hexdigest()[:16])
    return sha256(":".join(values).encode("ascii")).hexdigest()[:16]

def register(app):
    @app.get("/api/release")
    def pd_release_version():
        response = jsonify(release=fingerprint(), status="ok")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
