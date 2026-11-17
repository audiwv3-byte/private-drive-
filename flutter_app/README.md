# PRIVATE DRIVE — independent Flutter prototype

This is a **separate, isolated Android prototype**. It does not modify the
Telegram Mini App, PythonAnywhere production instance, customer database, or payments.

The current UI has phone/email selection and OTP verification screens.
It **does not create an app account or authenticated session**. The Python
OTP WSGI application is isolated and not mounted in production. Twilio
delivery is disabled unless separately authorized and configured.

## Local build

Install Flutter stable and Android SDK. Then:

```bash
flutter create --platforms=android --org=lt.privatedrive --project-name=private_drive private_drive_build
cp flutter_app/lib/main.dart private_drive_build/lib/main.dart
cd private_drive_build
flutter pub get
flutter analyze
flutter build apk --debug
```

The debug APK is a prototype for internal testing, **not a Play Store release**.
Do not add API secrets to the APK. Configure an HTTPS backend URL only when
native authentication has been securely deployed, rate-limited, and verified.

## GitHub Actions

The workflow `.github/workflows/flutter-prototype-apk.yml` generates a
standard Flutter Android scaffold and uploads a debug APK as an Actions
artifact. This avoids modifying the existing Telegram/Python application.
