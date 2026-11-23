"""Guard Android token backup on generated temporary Flutter project only."""
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from harden_android_native_auth import harden_android

A = "{http://schemas.android.com/apk/res/android}"


class AndroidNativeBackupTests(unittest.TestCase):
    def test_backup_and_device_transfer_disabled_on_generated_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            manifest = project / "android/app/src/main/AndroidManifest.xml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                '<application android:label="PRIVATE DRIVE">'
                '<activity android:name=".MainActivity"/>'
                '</application></manifest>', encoding="utf-8"
            )
            harden_android(project)
            harden_android(project)  # idempotent
            app = ET.parse(manifest).getroot().find("application")
            self.assertEqual(app.get(A+"allowBackup"),"false")
            self.assertEqual(app.get(A+"fullBackupContent"),"@xml/pd_native_no_backup")
            self.assertEqual(app.get(A+"dataExtractionRules"),"@xml/pd_native_no_extract")
            rules = manifest.parent / "res/xml"
            legacy = ET.parse(rules/"pd_native_no_backup.xml").getroot()
            self.assertEqual(legacy.tag,"full-backup-content")
            self.assertIn("sharedpref", [e.get("domain") for e in legacy])
            extraction=ET.parse(rules/"pd_native_no_extract.xml").getroot()
            self.assertEqual(extraction.tag,"data-extraction-rules")
            self.assertEqual([x.tag for x in extraction],["cloud-backup","device-transfer"])
            self.assertTrue(all(x.find("exclude") is not None for x in extraction))
            self.assertEqual(len(app.findall("activity")),1)

    def test_never_creates_an_unexpected_android_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                harden_android(Path(tmp))


if __name__=="__main__":
    unittest.main()
