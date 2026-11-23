"""Generate the public browser configuration during the Render static build."""
import json
import os
import re
from pathlib import Path

token = os.environ.get("MAPBOX_WEB_PUBLIC_TOKEN", "").strip()
if token and not re.fullmatch(r"pk\.[A-Za-z0-9_.-]+", token):
    raise SystemExit("MAPBOX_WEB_PUBLIC_TOKEN must be a public Mapbox token")
config = Path(__file__).resolve().parent / "site_preview" / "assets" / "mapbox-config.js"
config.write_text("window.PD_MAPBOX_PUBLIC_TOKEN = " + json.dumps(token) + ";\n", encoding="utf-8")
