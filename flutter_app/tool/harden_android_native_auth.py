#!/usr/bin/env python3
"""Harden ephemeral generated Flutter Android manifest, never modify live APK.

Used only for future internal Android build staging; also tested on synthetic
flutter-create Android fixtures in GitHub Actions. No release signing access.
"""
import sys
import re
from pathlib import Path
from xml.etree import ElementTree as ET

A = "{http://schemas.android.com/apk/res/android}"


def harden_android(project: Path) -> None:
    manifest = project / "android/app/src/main/AndroidManifest.xml"
    if not manifest.is_file():
        raise FileNotFoundError("generated AndroidManifest.xml required")
    # Preserve the original android: prefixes and Flutter embedding v2
    # metadata. ElementTree re-serialization changes the prefix and can
    # break Flutter's embedding detection in generated Android projects.
    text = manifest.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    if root.find("application") is None:
        raise ValueError("Android application element missing")
    if 'xmlns:android=' not in text:
        raise ValueError("Android namespace is required")
    match = re.search(r"<application\\b[^>]*>", text, flags=re.DOTALL)
    if match is None:
        raise ValueError("Android application opening tag missing")
    app_tag = match.group(0)
    for attribute, value in (
        ("allowBackup", "false"),
        ("fullBackupContent", "@xml/pd_native_no_backup"),
        ("dataExtractionRules", "@xml/pd_native_no_extract"),
    ):
        pattern = r'android:' + attribute + r'\\s*=\\s*["\\x27][^"\\x27]*["\\x27]'
        replacement = 'android:' + attribute + '="' + value + '"'
        if re.search(pattern, app_tag):
            app_tag = re.sub(pattern, replacement, app_tag)
        else:
            app_tag = app_tag[:-1] + ' ' + replacement + '>'
    updated = text[:match.start()] + app_tag + text[match.end():]
    ET.fromstring(updated)  # Reject malformed XML before writing.
    manifest.write_text(updated, encoding="utf-8")

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
