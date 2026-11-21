# PRIVATE DRIVE — Android camera permission for pilot identity preview

Status: TEST branch only; no deployment, photo capture, upload, biometric comparison or microphone recording.

## Confirmed build layout

The repository does not commit a `flutter_app/android/app/src/main/AndroidManifest.xml`. Its Android workflows generate `private_drive_build/android/app/src/main/AndroidManifest.xml` using `flutter create --platforms=android`, then patch the generated manifest in CI.

The following build pipelines now add to the generated Android manifest before compiling:

- `.github/workflows/flutter-prototype-apk.yml` — unsigned Android AAB test build.
- `.github/workflows/private-drive-signed-android-apk.yml` — internal test APK workflow (separately protected by existing signing secrets).

Exact generated declarations:

```xml
<uses-permission android:name="android.permission.CAMERA"/>
<uses-feature android:name="android.hardware.camera" android:required="false"/>
```

These do not start the camera or grant permission automatically. `PdPilotIdentityCheckPage` requests camera permission **only after the driver presses the on-screen button** using `permission_handler`. It never starts a camera stream, records images, stores files or sends data. It never marks the driver's identity verified.

No `RECORD_AUDIO` permission is added. Microphone access is not part of the face-check preview.

## Verification

- CI Flutter #652 and Android #705 failed on two widget tests: a removed booking button accessed after submission, and the pilot map button pushed below the test viewport by the new identity-check button.
- Minimal updates were made only to `flutter_app/test/demo_trip_flow_test.dart` and `flutter_app/test/pilot_cabin_test.dart`.
- Do not claim a successful rebuilt AAB/APK or runtime Android camera prompt until the relevant newer CI steps and device test complete.

Before actual identity checks: obtain a lawful GDPR basis, provider selection, robust session authorization, secure photo retention and deletion arrangements, manual appeal, approved UI consent and a genuine physical Android camera test. The current screen is a permission-only proposal.
