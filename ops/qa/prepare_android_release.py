"""Prepare a generated Android scaffold for isolated release-mode QA only."""
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
package = sys.argv[2] if len(sys.argv) > 2 else "lt.privatedrive.qa.private_drive"
label = sys.argv[3] if len(sys.argv) > 3 else "PRIVATE DRIVE QA ONLY"
gradle = root / "android/app/build.gradle.kts"
s = gradle.read_text()
for key in ("compileSdk", "targetSdk"):
    s, n = re.subn(r"(?m)^(\s*" + key + r"\s*=\s*)[^\n]+", r"\g<1>36", s)
    assert n == 1, key
assert f'applicationId = "{package}"' in s
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
app.set("{" + ns + "}label", label)
existing = {p.get("{" + ns + "}name") for p in doc.findall("uses-permission")}
for name in ("INTERNET", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "CAMERA", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_LOCATION", "WAKE_LOCK", "POST_NOTIFICATIONS"):
    full = "android.permission." + name
    if full not in existing:
        doc.insert(0, ET.Element("uses-permission", {"{" + ns + "}name": full}))
tree.write(manifest, encoding="utf-8", xml_declaration=True)

# The release-only scaffold must not register Flutter's debug-only integration
# test plugin. Keep the original app pubspec and test suite unchanged.
pubspec = root / "pubspec.yaml"
source = pubspec.read_text()
source, count = re.subn(r"(?m)^  integration_test:\s*\n    sdk: flutter[ \t]*\n", "", source)
assert count == 1, "Expected one integration_test SDK dev dependency"
pubspec.write_text(source)
print("Removed integration_test from isolated release scaffold only")
