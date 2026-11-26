"""QA38 source gate audit; not a certification of production readiness."""
from pathlib import Path
import re
root=Path("flutter_app/lib")
main=(root/"main.dart").read_text()
cabin=(root/"native_cabin_entry.dart").read_text()
pilot=(root/"native_pilot_orders.dart").read_text()
assert "bool.fromEnvironment('PD_INTERNAL_QA') && _guest" in main
assert "bool.fromEnvironment('PD_INTERNAL_QA') && _localQaPin != ''" in cabin
# Follow the normal Dart entry point. Debug GPS exceptions belong only to
# the isolated historical fixtures, including when imported indirectly.
pending = [(root / "main.dart").resolve()]
visited = set()
while pending:
    path = pending.pop()
    if path in visited:
        continue
    visited.add(path)
    for name in re.findall(r"""(?:import|export|part) ['"]([^'"]+)['"]""", path.read_text()):
        if ":" not in name:
            pending.append((path.parent / name).resolve())
assert (root / "qa_pilot_transport.dart").resolve() not in visited
assert "PdHttpApi.configuredOrigin" in pilot
assert "PD_QA" not in pilot and "PD_INTERNAL_QA" not in pilot
assert "kIsWeb && isolatedWebPreview" in main
print("PASS explicit source-level guest, local PIN, web preview and isolated GPS transport")
print("PUBLIC RELEASE BLOCKERS (not waived):")
print("1. Authenticated cabins still use PrivateDriveDemo and local trip logic.")
print("2. Store signing, verified public backend and device runtime not tested.")
print("3. Foreground-only QA38 iOS profile removes background capability in runner only.")
print("This CI builds non-distributable isolated release-mode binaries, not store-ready apps.")
