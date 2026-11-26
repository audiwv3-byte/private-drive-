"""QA38 source gate audit; not a certification of production readiness."""
from pathlib import Path
import json
root=Path("flutter_app/lib")
main=(root/"main.dart").read_text()
cabin=(root/"native_cabin_entry.dart").read_text()
pilot=(root/"native_pilot_orders.dart").read_text()
assert "bool.fromEnvironment('PD_INTERNAL_QA') && _guest" in main
assert "bool.fromEnvironment('PD_INTERNAL_QA') && _localQaPin != ''" in cabin
assert "bool.fromEnvironment('PD_QA28_GPS')" in pilot
assert "bool.fromEnvironment('PD_INTERNAL_QA')" in pilot
assert "qaGpsEnabled && kDebugMode" in pilot
assert "kIsWeb && isolatedWebPreview" in main
print("PASS explicit source-level guest, local PIN, web preview and GPS QA gates")
print("PUBLIC RELEASE BLOCKERS (not waived):")
print("1. Authenticated cabins still use PrivateDriveDemo and local trip logic.")
print("2. Pilot API restricts host to staging; GPS upload requires internal QA flags.")
print("3. Store signing, verified public backend and device runtime not tested.")
print("4. Foreground-only QA38 iOS profile removes background capability in runner only.")
print("This CI builds non-distributable isolated release-mode binaries, not store-ready apps.")
