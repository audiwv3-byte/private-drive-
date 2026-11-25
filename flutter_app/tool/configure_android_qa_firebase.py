"""Configure the generated Android QA project from its registered Firebase app."""
import json
import os
from pathlib import Path

project = "private-drive-197bf"
package = "lt.privatedrive.private_drive.photo_qa"
try:
    config = json.loads(os.environ["PD_FIREBASE_ANDROID_CONFIG"])
    clients = [
        client for client in config["client"]
        if client["client_info"]["android_client_info"]["package_name"] == package
    ]
    if config["project_info"]["project_id"] != project or len(clients) != 1:
        raise ValueError("wrong project or app")
except (KeyError, TypeError, ValueError):
    raise SystemExit("Firebase config must match PRIVATE DRIVE Android QA.") from None

for filename, plugin in (
    ("android/settings.gradle.kts", 'id("com.google.gms.google-services") version "4.4.4" apply false'),
    ("android/app/build.gradle.kts", 'id("com.google.gms.google-services")'),
):
    file = Path(filename)
    source = file.read_text()
    marker = "plugins {"
    if source.count(marker) != 1:
        raise SystemExit(f"Missing plugins block in {filename}")
    file.write_text(source.replace(marker, f"{marker}\n    {plugin}", 1))

Path("android/app/google-services.json").write_text(json.dumps(config))
