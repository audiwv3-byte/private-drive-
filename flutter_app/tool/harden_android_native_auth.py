#!/usr/bin/env python3
"""Harden ephemeral generated Flutter Android manifest, never modify live APK.

Used only for future internal Android build staging; also tested on synthetic
flutter-create Android fixtures in GitHub Actions. No release signing access.
"""
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

A = "{http://schemas.android.com/apk/res/android}"


def harden_android(project: Path) -> None:
    manifest = project / "android/app/src/main/AndroidManifest.xml"
    if not manifest.is_file():
        raise FileNotFoundError("generated AndroidManifest.xml required")
    xml = ET.parse(manifest)
    root = xml.getroot()
    app = root.find("application")
    if app is None:
        raise ValueError("Android application element missing")
    app.set(A + "allowBackup", "false")
    app.set(A + "fullBackupContent", "@xml/pd_native_no_backup")
    app.set(A + "dataExtractionRules", "@xml/pd_native_no_extract")
    xml.write(manifest, encoding="unicode", xml_declaration=True)

    folder = manifest.parent / "res/xml"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pd_native_no_backup.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<full-backup-content>\n'
        '  <exclude domain="root" path="."/>\n'
        '  <exclude domain="sharedpref" path="."/>\n'
        '  <exclude domain="database" path="."/>\n'
        '  <exclude domain="file" path="."/>\n'
        '</full-backup-content>\n', encoding="utf-8"
    )
    (folder / "pd_native_no_extract.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<data-extraction-rules>\n'
        '  <cloud-backup><exclude domain="root" path="."/></cloud-backup>\n'
        '  <device-transfer><exclude domain="root" path="."/></device-transfer>\n'
        '</data-extraction-rules>\n', encoding="utf-8"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: harden_android_native_auth.py GENERATED_PROJECT")
    harden_android(Path(sys.argv[1]))
