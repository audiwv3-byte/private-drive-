import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_session_manager.dart';
import 'package:private_drive/native_session_vault.dart';
import 'package:private_drive/native_logout_api.dart';
import 'package:private_drive/pilot_identity_api.dart';
import 'package:private_drive/pilot_identity_notice_page.dart';
import 'package:private_drive/pilot_cabin.dart';

const baseUrl = 'https://auth.example.test';
const testToken = 'synthetic-device-token-abcdefghijklmnopqrstuvwxyz1234567890';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  PdNativeSession session({String role = 'passenger'}) => PdNativeSession(
    token: testToken, userId: 'verified-user', role: role,
    expiresAt: DateTime.now().add(const Duration(hours: 3)),
  );

  Future<void> tap(WidgetTester tester, String key) async {
    final finder = find.byKey(Key(key));
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }

  Future<void> pumpRestored(WidgetTester tester, {
    required http.Client client,
    required PdNativeSessionVault vault,
    String? role,
  }) async {
    final manager = PdNativeSessionManager(
      baseUrl: baseUrl, vault: vault, client: client,
    );
    await tester.pumpWidget(MaterialApp(home: PdNativeCabinEntry(
      sessionManager: manager,
      logoutApi: PdNativeLogoutApi(baseUrl: baseUrl, client: client),
      signInBuilder: (_, requested, authenticated) => Scaffold(
        body: FilledButton(
          key: const Key('synthetic-otp-auth'),
          onPressed: () => authenticated(session(role: role ?? 'passenger')),
          child: const Text('Test verified OTP'),
        ),
      ),
      identityApiBuilder: (active) => PdIdentityApi(
        baseUrl: baseUrl, token: active.token, client: client,
      ),
    )));
    await tester.pumpAndSettle();
  }

  MockClient mockServer({
    required String role,
    bool online = true,
    bool canLogout = true,
    List<http.Request>? events,
  }) => MockClient((request) async {
    events?.add(request);
    if (!online) throw Exception('synthetic network outage');
    if (request.url.path == '/native-auth/session') {
      expect(request.method, 'GET');
      expect(request.headers['authorization'], 'Bearer $testToken');
      expect(request.url.query, isEmpty);
      expect(request.body, isEmpty);
      return http.Response(jsonEncode({
        'user_id': 'verified-user',
        'role': role,
        'expires_at': DateTime.now().add(const Duration(hours: 2))
            .millisecondsSinceEpoch ~/ 1000,
      }), 200);
    }
    if (request.url.path == '/native-auth/logout') {
      expect(request.method, 'POST');
      expect(request.headers['authorization'], 'Bearer $testToken');
      expect(request.url.query, isEmpty);
      expect(request.body, isEmpty);
      return canLogout
          ? http.Response('{"status":"logged_out"}', 200)
          : http.Response('{"error":"server_unavailable"}', 503);
    }
    return http.Response('{"status":"pending"}', 200);
  });

  testWidgets('passenger cold restart restores verified session and requires cabinet selection',
      (tester) async {
    const vault = PdNativeSessionVault();
    await vault.save(session());
    final events = <http.Request>[];
    final client = mockServer(role: 'passenger', events: events);
    addTearDown(client.close);
    await pumpRestored(tester, client: client, vault: vault);
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
    expect(find.byTooltip('Выйти'), findsOneWidget);
    expect(events.where((r) => r.url.path == '/native-auth/session'), hasLength(1));
    await tap(tester, 'entry-passenger');
    final skip = find.byKey(const Key('permission-onboarding-skip'));
    if (skip.evaluate().isNotEmpty) await tap(tester, 'permission-onboarding-skip');
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(find.byType(PilotCabin), findsNothing);
  });

  testWidgets('pilot cold restart requires photo flow and cannot skip verification',
      (tester) async {
    const vault = PdNativeSessionVault();
    await vault.save(session(role:'pilot'));
    final client=mockServer(role:'pilot');
    addTearDown(client.close);
    await pumpRestored(tester, client:client, vault:vault);
    await tap(tester,'entry-pilot');
    expect(find.byType(PdPilotIdentityNoticePage), findsOneWidget);
    expect(find.byType(PilotCabin), findsNothing);
  });

  testWidgets('admin restored with server role can select dispatcher without OTP',
      (tester) async {
    const vault=PdNativeSessionVault();
    await vault.save(session(role:'admin'));
    final client=mockServer(role:'admin');
    addTearDown(client.close);
    await pumpRestored(tester, client:client, vault:vault);
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
    await tap(tester,'entry-dispatcher');
    final skip=find.byKey(const Key('permission-onboarding-skip'));
    if(skip.evaluate().isNotEmpty) await tap(tester,'permission-onboarding-skip');
    expect(find.byKey(const Key('dispatcher-open-drawer')),findsOneWidget);
  });

  testWidgets('server downgrade from pilot to passenger blocks pilot cabinet',
      (tester) async {
    const vault=PdNativeSessionVault();
    await vault.save(session(role:'pilot'));
    final client=mockServer(role:'passenger');
    addTearDown(client.close);
    await pumpRestored(tester, client:client, vault:vault);
    await tap(tester,'entry-pilot');
    expect(find.byType(PdPilotIdentityNoticePage),findsOneWidget);
    expect(find.byType(PilotCabin),findsNothing);
    expect(find.byKey(const Key('pilot-identity-notice-sign-in')),
      findsOneWidget);
  });

  testWidgets('offline cold restart cannot grant any cabin and retains encrypted token',
      (tester) async {
    const vault=PdNativeSessionVault();
    await vault.save(session(role:'admin'));
    final client=mockServer(role:'admin',online:false);
    addTearDown(client.close);
    await pumpRestored(tester, client:client, vault:vault);
    expect(find.byKey(const Key('entry-cabin-selection')),findsOneWidget);
    expect(find.byTooltip('Выйти'),findsNothing);
    expect(find.byKey(const Key('dispatcher-open-drawer')),findsNothing);
    expect((await vault.read())?.token,testToken);
    await tap(tester,'entry-dispatcher');
    expect(find.byKey(const Key('entry-test-sign-in')),findsNothing);
    expect(find.byKey(const Key('dispatcher-open-drawer')),findsNothing);
  });

  testWidgets('confirmed logout clears stored token and next cold start cannot restore',
      (tester) async {
    const vault=PdNativeSessionVault();
    await vault.save(session());
    final events=<http.Request>[];
    final client=mockServer(role:'passenger',events:events);
    addTearDown(client.close);
    await pumpRestored(tester, client:client, vault:vault);
    await tester.tap(find.byTooltip('Выйти'));
    await tester.pumpAndSettle();
    expect(await vault.read(),isNull);
    expect(find.byTooltip('Выйти'),findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await pumpRestored(tester,client:client,vault:vault);
    expect(find.byTooltip('Выйти'),findsNothing);
    expect(events.where((e)=>e.url.path=='/native-auth/logout'),hasLength(1));
  });

  testWidgets('failed logout keeps encrypted token and permits next restart',
      (tester) async {
    const vault=PdNativeSessionVault();
    await vault.save(session());
    final client=mockServer(role:'passenger',canLogout:false);
    addTearDown(client.close);
    await pumpRestored(tester,client:client,vault:vault);
    await tester.tap(find.byTooltip('Выйти'));
    await tester.pumpAndSettle();
    expect((await vault.read())?.token,testToken);
    expect(find.byTooltip('Выйти'),findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await pumpRestored(tester,client:client,vault:vault);
    expect(find.byTooltip('Выйти'),findsOneWidget);
  });
}
