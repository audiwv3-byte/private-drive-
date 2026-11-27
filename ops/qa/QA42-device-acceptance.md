# QA42 device acceptance preparation

Base: dca6ceb2a58ad73b24099ac4adfb0ca9e9c0e857 (QA41 PASS). APK applicationId lt.privatedrive.qa.device42; ephemeral signing key; no overwrite of installed app. API origin https://qa.invalid intentionally nonfunctional. No mobile QA flags. Do not enter real credentials.

## Device test environment (not provisioned)
Use a separate, explicitly approved isolated machine on private test Wi-Fi/VPN, local PostgreSQL private_drive_test, synthetic users and short-lived credentials, no live SMS or payment providers. Existing pd_qa25_wsgi is only an order/assignment/GPS fixture: before connecting phones, implement and test isolated native authentication and dispatcher login, verify all API contracts, deny external egress and production hosts. Use a distinct hostname with trusted TLS on port 443, no certificate bypass, no public tunnel or hosting changes. Build both clients with that exact HTTPS origin after verification. Do not remove server QA safety gates.

iOS: use isolated bundle ID lt.privatedrive.qa.privateDrive, retain background location capability and ATS. Build signed device app through Xcode with authorized Apple development team and registered test device, or separately approved TestFlight workflow. No signing credentials in repository or chat. No store upload in QA42 preparation.

## Acceptance
Record build SHA, package/bundle ID, signing fingerprint, OS version and device model. Install only isolated builds with explicit device approval. Verify synthetic login, passenger order, dispatcher assignment, consent refusal, GPS start, locked screen, reconnection, manual stop and completion; verify PostgreSQL and dispatcher evidence, no location after stop. Do not use actual passenger data. Physical tests remain pending until device access and test API are available.
