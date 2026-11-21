import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/pilot_identity_check_page.dart';
import 'package:private_drive/pilot_identity_api.dart';
import 'package:private_drive/pilot_photo_capture.dart';

class FakeCamera implements PdPilotCameraPermission {
  FakeCamera({this.granted = true, this.fail = false});
  final bool granted;
  final bool fail;
  int requests = 0;
  @override
  Future<bool> requestCamera() async {
    requests++;
    if (fail) throw StateError('synthetic');
    return granted;
  }
}
class FakePhoto implements PdPilotPhotoCapture {
  FakePhoto(this.photo);
  final Uint8List? photo;
  int captures = 0;
  @override
  Future<Uint8List?> capture() async { captures++; return photo; }
}
void main() {
  final photo = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGJkAAAAASUVORK5CYII=');
  Future<void> tap(WidgetTester tester, String key) async {
    final finder = find.byKey(Key(key));
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }
  testWidgets('QA skip is gated and does not capture or grant identity', (tester) async {
    var skipped = false;
    final camera = FakeCamera();
    final capture = FakePhoto(photo);
    await tester.pumpWidget(MaterialApp(home: PdPilotIdentityCheckPage(
      cameraPermission: camera, photoCapture: capture,
      onContinueWithoutVerification: () => skipped = true)));
    final skip = find.byKey(const Key('pilot-identity-qa-skip'));
    if (const bool.fromEnvironment('PD_INTERNAL_QA')) {
      await tap(tester, 'pilot-identity-qa-skip');
      expect(skipped, isTrue);
      expect(find.textContaining('Личность не подтверждена'), findsOneWidget);
    } else {
      expect(skip, findsNothing);
      expect(skipped, isFalse);
    }
    expect(camera.requests, 0);
    expect(capture.captures, 0);
    expect(find.text('Проверка личности не выполнена'), findsOneWidget);
  });
  for (final outcome in ['denied', 'cancelled', 'error']) {
    testWidgets('Camera $outcome leaves cabin accessible without verification', (tester) async {
      final camera = FakeCamera(granted: outcome != 'denied', fail: outcome == 'error');
      final capture = FakePhoto(null);
      await tester.pumpWidget(MaterialApp(home: PdPilotIdentityCheckPage(
        cameraPermission: camera, photoCapture: capture)));
      expect(camera.requests, 0);
      await tap(tester, 'pilot-identity-request-camera');
      expect(camera.requests, 1);
      expect(capture.captures, outcome == 'cancelled' ? 1 : 0);
      expect(find.text('Проверка личности не выполнена'), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('pilot-identity-back')));
      expect(tester.widget<TextButton>(find.byKey(const Key('pilot-identity-back'))).onPressed, isNotNull);
    });
  }
  testWidgets('Capture preview retake and explicit upload wait for reviewer', (tester) async {
    var uploads = 0;
    final client = MockClient((req) async {
      expect(req.headers['Authorization'], 'Bearer synthetic-token');
      if (req.url.path.endsWith('/submit')) {
        uploads++;
        expect((jsonDecode(req.body) as Map)['photo'], base64Encode(photo));
        return http.Response('{"status":"pending"}', 202);
      }
      return http.Response('{"status":"approved"}', 200);
    });
    addTearDown(client.close);
    final capture = FakePhoto(photo);
    await tester.pumpWidget(MaterialApp(home: PdPilotIdentityCheckPage(
      cameraPermission: FakeCamera(), photoCapture: capture,
      api: PdIdentityApi(baseUrl: 'https://example.test', token: 'synthetic-token', client: client))));
    expect(uploads, 0);
    await tap(tester, 'pilot-identity-request-camera');
    expect(find.byKey(const Key('pilot-identity-photo-preview')), findsOneWidget);
    expect(uploads, 0);
    await tap(tester, 'pilot-identity-request-camera');
    expect(capture.captures, 2);
    await tap(tester, 'pilot-identity-submit');
    expect(uploads, 1);
    expect(find.textContaining('ожидает проверки диспетчером'), findsOneWidget);
    expect(find.text('Личность подтверждена диспетчером'), findsNothing);
    expect(find.byKey(const Key('pilot-identity-photo-preview')), findsNothing);
    await tap(tester, 'pilot-identity-refresh');
    expect(find.text('Личность подтверждена диспетчером'), findsOneWidget);
  });
  testWidgets('Failed upload keeps preview and retry never marks approved', (tester) async {
    var calls = 0;
    final client = MockClient((req) async { calls++; return http.Response('{}', 503); });
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: PdPilotIdentityCheckPage(
      cameraPermission: FakeCamera(), photoCapture: FakePhoto(photo),
      api: PdIdentityApi(baseUrl: 'https://example.test', token: 'token', client: client))));
    await tap(tester, 'pilot-identity-request-camera');
    await tap(tester, 'pilot-identity-submit');
    expect(calls, 1);
    expect(find.byKey(const Key('pilot-identity-photo-preview')), findsOneWidget);
    expect(find.text('Проверка личности не выполнена'), findsOneWidget);
    await tap(tester, 'pilot-identity-submit');
    expect(calls, 2);
  });
}

