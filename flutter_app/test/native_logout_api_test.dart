import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/native_logout_api.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/pilot_identity_api.dart';

const token = 'test-local-device-token-abcdefghijklmnopqrstuvwxyz1234567890';

void main() {
  test('logout uses HTTPS, POST, Authorization only and an empty body', () async {
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.toString(),
          'https://auth.example.test/native-auth/logout');
      expect(request.url.query, isEmpty);
      expect(request.headers['authorization'], 'Bearer $token');
      expect(request.body, isEmpty);
      expect(request.url.toString(), isNot(contains(token)));
      return http.Response('{"status":"logged_out"}', 200);
    });
    await PdNativeLogoutApi(baseUrl: 'https://auth.example.test',
      client: client).revokeCurrentDevice(token);
    client.close();
  });

  test('failed logout stays failed and never treats a 401 as success', () async {
    final client = MockClient((_) async =>
      http.Response('{"error":"invalid_session"}', 401));
    await expectLater(
      PdNativeLogoutApi(baseUrl: 'https://auth.example.test',
        client: client).revokeCurrentDevice(token),
      throwsA(isA<Exception>()),
    );
    client.close();
  });

  test('rejects http origin, invalid token and a false success payload', () async {
    final client = MockClient((_) async =>
      http.Response('{"status":"other"}', 200));
    await expectLater(PdNativeLogoutApi(baseUrl: 'http://example.test',
      client: client).revokeCurrentDevice(token), throwsFormatException);
    await expectLater(PdNativeLogoutApi(baseUrl: 'https://example.test',
      client: client).revokeCurrentDevice('bad'), throwsFormatException);
    await expectLater(PdNativeLogoutApi(baseUrl: 'https://example.test',
      client: client).revokeCurrentDevice(token), throwsA(isA<Exception>()));
    client.close();
  });

  Future<void> setupEntry(WidgetTester tester, http.Client client) async {
    await tester.pumpWidget(MaterialApp(home: PdNativeCabinEntry(
      logoutApi: PdNativeLogoutApi(baseUrl: 'https://auth.example.test',
        client: client),
      signInBuilder: (_, role, authenticated) => Scaffold(
        body: FilledButton(
          key: const Key('authenticate'),
          onPressed: () => authenticated(PdNativeSession(token: token,
            userId: 'synthetic-passenger', role: 'passenger',
            expiresAt: DateTime.now().add(const Duration(hours: 1)))),
          child: const Text('authenticate'),
        ),
      ),
      identityApiBuilder: (session) => PdIdentityApi(
        baseUrl: 'https://auth.example.test',
        token: session.token, client: client),
    )));
    await tester.tap(find.byKey(const Key('entry-dispatcher')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('authenticate')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('entry-role-message')), findsOneWidget);
  }

  testWidgets('successful logout clears only this local in-memory session',
      (tester) async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      return http.Response('{"status":"logged_out"}', 200);
    });
    addTearDown(client.close);
    await setupEntry(tester, client);
    expect(find.byTooltip('Выйти'), findsOneWidget);
    await tester.tap(find.byTooltip('Выйти'));
    await tester.pumpAndSettle();
    expect(requests, hasLength(1));
    expect(requests.single.headers['authorization'], 'Bearer $token');
    expect(requests.single.body, isEmpty);
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
    expect(find.byTooltip('Выйти'), findsNothing);
  });

  testWidgets('HTTP failure preserves local session and allows retry',
      (tester) async {
    var attempts = 0;
    final client = MockClient((request) async {
      attempts++;
      if (attempts == 1) return http.Response('{"error":"server_error"}', 503);
      return http.Response('{"status":"logged_out"}', 200);
    });
    addTearDown(client.close);
    await setupEntry(tester, client);
    await tester.tap(find.byTooltip('Выйти'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Выйти'), findsOneWidget);
    expect(attempts, 1);
    await tester.tap(find.byTooltip('Выйти'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.byTooltip('Выйти'), findsNothing);
  });
}
