"""Prepare a generated Android scaffold for isolated release-mode QA only."""
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
gradle = root / "android/app/build.gradle.kts"
s = gradle.read_text()
for key in ("compileSdk", "targetSdk"):
    s, n = re.subn(r"(?m)^(\s*" + key + r"\s*=\s*)[^\n]+", r"\g<1>36", s)
    assert n == 1, key
assert 'applicationId = "lt.privatedrive.qa.private_drive"' in s
assert 'signingConfig = signingConfigs.getByName("debug")' in s
gradle.write_text(s)
manifest = root / "android/app/src/main/AndroidManifest.xml"
ns = "http://schemas.android.com/apk/res/android"
ET.register_namespace("android", ns)
tree = ET.parse(manifest)
doc = tree.getroot()
app = doc.find("application")
assert app is not None
app.set("{" + ns + "}usesCleartextTraffic", "false")
app.set("{" + ns + "}allowBackup", "false")
app.set("{" + ns + "}label", "PRIVATE DRIVE QA ONLY")
existing = {p.get("{" + ns + "}name") for p in doc.findall("uses-permission")}
for name in ("INTERNET", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "CAMERA", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_LOCATION", "WAKE_LOCK", "POST_NOTIFICATIONS"):
    full = "android.permission." + name
    if full not in existing:
        doc.insert(0, ET.Element("uses-permission", {"{" + ns + "}name": full}))
tree.write(manifest, encoding="utf-8", xml_declaration=True)
