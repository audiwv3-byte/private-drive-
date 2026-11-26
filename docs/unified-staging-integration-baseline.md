# Integration baseline

Android base: 0ed1e60482f30aa5039d7f0ef170144949a4e2ec
Orders QA: 0a17bef4f494834c0e61d402d3ed3f3373ea808b
Dispatcher: 44795f496ed05760cfc09474c506c6d7916c86fb
Telegram QA: d5ef3ec94fbd7f17db4f1a6ab92f48c0362f56ba

Android and orders QA diverged: 54 Android-only and 372 QA-only commits. Both sides changed the following paths (potential conflicts, not confirmed Git conflicts):

- flutter_app/lib/demo_interfaces.dart
- flutter_app/lib/main.dart
- flutter_app/lib/native_cabin_entry.dart
- flutter_app/lib/passenger_demo.dart
- flutter_app/lib/passenger_ride_entry.dart
- flutter_app/lib/pd_http_api.dart
- flutter_app/lib/pilot_cabin.dart
- flutter_app/lib/remote_sync_demo.dart
- flutter_app/pubspec.yaml
- flutter_app/test/remote_sync_demo_test.dart
- isolated_sms_wsgi.py
- pd_native_auth_postgres_http.py
- pd_native_auth_postgres_session_lifecycle.py
- pd_native_identity_http.py
- pd_native_pilot_assignment.py

Local git ls-remote failed DNS resolution. No trial merge performed. Preserve Android UI and run regression tests before accepting integration. No deployment, SMS or payments. Telegram deployed revision and Android 0.2.43 binary provenance remain unverified.
