"""Check final AAB manifest, not only the source manifest."""
import sys
import xml.etree.ElementTree as ET

doc = ET.parse(sys.argv[1]).getroot()
a = "{http://schemas.android.com/apk/res/android}"
assert doc.get("package") == "lt.privatedrive.qa.private_drive"
sdk = doc.find("uses-sdk")
assert sdk is not None and sdk.get(a + "targetSdkVersion") == "36"
app = doc.find("application")
assert app is not None
assert app.get(a + "debuggable", "false") == "false"
assert app.get(a + "usesCleartextTraffic") == "false"
assert app.get(a + "allowBackup") == "false"
permissions = {p.get(a + "name") for p in doc if p.tag.startswith("uses-permission")}
required = {"INTERNET", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "CAMERA", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_LOCATION"}
assert {"android.permission." + x for x in required} <= permissions
forbidden = {"ACCESS_BACKGROUND_LOCATION", "READ_CONTACTS", "WRITE_CONTACTS", "READ_SMS", "SEND_SMS", "RECEIVE_SMS", "READ_CALL_LOG", "WRITE_CALL_LOG", "CALL_PHONE", "RECORD_AUDIO", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES", "REQUEST_INSTALL_PACKAGES"}
assert not ({"android.permission." + x for x in forbidden} & permissions), sorted(permissions)
print("PASS isolated package, API 36, non-debuggable, TLS-only, backup disabled")
print("Final permissions:", *sorted(permissions), sep="\n")
