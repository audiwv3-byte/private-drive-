# PRIVATE DRIVE — isolated Android demo signing

This is a **test-only**, deliberately public debug signing certificate.
It is NOT a production credential and MUST NOT sign production or
private-distribution builds.

- Android application ID: `lt.privatedrive.private_drive.demo`
- Visible Android app name: `PRIVATE DRIVE DEMO`
- Debug signing key: `flutter_app/demo_debug_signing_key.b64`
- Keystore type: JKS; alias: `AndroidDebugKey`; known debug passwords
- Version: `0.2.0+20261118` at the branded icon release

The demo application ID is intentionally distinct from the earlier
prototype and any future production build. This lets both installations
coexist and prevents accidental update/signature conflicts.

For every subsequent demo APK, keep the key and application ID unchanged
so Android can install updates in place. For production, use a separate
package name and a privately managed signing key.
