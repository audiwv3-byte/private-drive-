import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_session_manager.dart';
import 'package:private_drive/native_session_vault.dart';
import 'package:private_drive/native_logout_api.dart';
import 'package:private_drive/pilot_identity_api.dart';
import 'package:private_drive/pilot_identity_notice_page.dart';
import 'package:private_drive/pilot_cabin.dart';

const _base = 'https://offline-auth.example.test';
const _token = 'isolated-widget-token-abcdefghijklmnopqrstuvwxyz01234567890';

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
  });

  PdNativeSession session(String role) => PdNativeSession(
    token: _token, userId: 'synthetic-account', role: role,
    expiresAt: DateTime.now().add(const Duration(hours: 3)),
  );

  Future<void> mount(
    WidgetTester tester, {
    required String storedRole,
    required String authoritativeRole,
    required List<http.Request> calls,
    bool logoutSucceeds = true,
  }) async {
    const vault = PdNativeSessionVault();
    await vault.save(session(storedRole));
    final client = MockClient((request) async {
      calls.add(request);
      expect(request.url.scheme, 'https');
      expect(request.url.host, 'offline-auth.example.test');
      if (request.url.path == '/native-auth/session') {
        expect(request.method, 'GET');
        expect(request.headers['authorization'], 'Bearer $_token');
        expect(request.body, isEmpty);
        return http.Response(jsonEncode({
          'user_id': 'synthetic-account',
          'role': authoritativeRole,
          'expires_at': DateTime.now()
              .add(const Duration(hours: 1)).millisecondsSinceEpoch ~/ 1000,
        }), 200);
      }
      if (request.url.path == '/native-auth/logout') {
        expect(request.method, 'POST');
        expect(request.headers['authorization'], 'Bearer $_token');
        expect(request.url.query, isEmpty);
        expect(request.body, isEmpty);
        return logoutSucceeds
            ? http.Response('{"status":"logged_out"}', 200)
            : http.Response('{"error":"database_unavailable"}', 503);
      }
      return http.Response('{"status":"pending"}', 200);
    });
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: PdNativeCabinEntry(
      sessionManager: PdNativeSessionManager(
        baseUrl: _base, vault: vault, client: client),
      logoutApi: PdNativeLogoutApi(baseUrl: _base, client: client),
      signInBuilder: (_, role, callback) => Scaffold(
        body: Text('AUTH_NEEDED:$role', key: const Key('auth-required'))),
      identityApiBuilder: (active) => PdIdentityApi(
        baseUrl: _base, token: active.token, client: client),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
  }

  Future<void> tap(WidgetTester tester, String key) async {
    await tester.ensureVisible(find.byKey(Key(key)));
    await tester.tap(find.byKey(Key(key)));
    await tester.pumpAndSettle();
  }

  Future<void> skipPermissions(WidgetTester tester) async {
    if (find.byKey(const Key('permission-onboarding-skip')).evaluate().isNotEmpty) {
      await tap(tester, 'permission-onboarding-skip');
    }
  }

  testWidgets('passenger restored session never exposes pilot earnings or dispatcher',
      (tester) async {
    final calls = <http.Request>[];
    await mount(tester, storedRole: 'passenger',
      authoritativeRole: 'passenger', calls: calls);
    await tap(tester, 'entry-passenger');
    await skipPermissions(tester);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-transfer')), findsOneWidget);
    expect(find.byKey(const Key('pilot-cockpit-earnings-toggle')), findsNothing);
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
    expect(find.byType(PilotCabin), findsNothing);
    await tester.tap(find.byType(BackButton).first);
    await tester.pumpAndSettle();
    await tap(tester, 'entry-dispatcher');
    expect(find.byKey(const Key('auth-required')), findsOneWidget);
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
    expect(calls.where((e) => e.url.path == '/native-auth/session'), hasLength(1));
  });

  testWidgets('dispatcher restored session has real dispatcher tabs and no fake GPS',
      (tester) async {
    final calls = <http.Request>[];
    await mount(tester, storedRole: 'dispatcher',
      authoritativeRole: 'dispatcher', calls: calls);
    await tap(tester, 'entry-dispatcher');
    await skipPermissions(tester);
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsOneWidget);
    expect(find.byKey(const Key('dispatcher-map-tab')), findsOneWidget);
    expect(find.textContaining('Подтверждённых GPS-точек нет'), findsOneWidget);
    expect(find.byKey(const Key('dispatcher-pilot-marker')), findsNothing);
    await tap(tester, 'dispatcher-open-drawer');
    expect(find.byKey(const Key('dispatcher-navigation-drawer')), findsOneWidget);
    await tap(tester, 'dispatcher-menu-2');
    expect(find.byKey(const Key('dispatcher-pilots-tab')), findsOneWidget);
    expect(find.byKey(const Key('pilot-cockpit-earnings-toggle')), findsNothing);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsNothing);
  });

  testWidgets('pilot_dispatcher and admin get dispatcher only after server check',
      (tester) async {
    for (final role in ['pilot_dispatcher', 'admin']) {
      await tester.pumpWidget(const SizedBox.shrink());
      FlutterSecureStorage.setMockInitialValues({});
      SharedPreferences.setMockInitialValues({});
      final calls = <http.Request>[];
      await mount(tester, storedRole: 'passenger',
        authoritativeRole: role, calls: calls);
      await tap(tester, 'entry-pilot');
      expect(find.byType(PdPilotIdentityNoticePage), findsOneWidget);
      expect(find.byType(PilotCabin), findsNothing);
      await tester.tap(find.byType(BackButton).first);
      await tester.pumpAndSettle();
      await tap(tester, 'entry-dispatcher');
      await skipPermissions(tester);
      expect(find.byKey(const Key('dispatcher-open-drawer')), findsOneWidget);
    }
  });

  testWidgets('confirmed passenger cabin logout clears only verified local session',
      (tester) async {
    const vault = PdNativeSessionVault();
    final calls = <http.Request>[];
    await mount(tester, storedRole: 'passenger',
      authoritativeRole: 'passenger', calls: calls);
    await tap(tester, 'entry-passenger');
    await skipPermissions(tester);
    await tap(tester, 'passenger-sign-out');
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
    expect(await vault.read(), isNull);
    expect(calls.where((r) => r.url.path == '/native-auth/logout'), hasLength(1));
  });

  testWidgets('logout server failure keeps restored session and encrypted token',
      (tester) async {
    const vault = PdNativeSessionVault();
    final calls = <http.Request>[];
    await mount(tester, storedRole: 'passenger',
      authoritativeRole: 'passenger', calls: calls, logoutSucceeds: false);
    await tap(tester, 'entry-passenger');
    await skipPermissions(tester);
    await tap(tester, 'passenger-sign-out');
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect((await vault.read())?.token, _token);
    expect(calls.where((r) => r.url.path == '/native-auth/logout'), hasLength(1));
  });

  test('GPS fix cannot exist while offline and clears as soon as pilot leaves line', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    store.updatePilotLocation(54.6872, 25.2797);
    expect(store.pilotLatitude, isNull);
    expect(store.pilotLastSeen, isNull);
    store.setPilotOnline(true);
    expect(store.pilotLatitude, isNull, reason: 'Online is not a GPS fix');
    store.updatePilotLocation(999, 25.2797);
    expect(store.pilotLatitude, isNull);
    store.updatePilotLocation(54.6872, 25.2797);
    expect(store.pilotLatitude, 54.6872);
    expect(store.pilotLastSeen, isNotNull);
    store.setPilotOnline(false);
    expect(store.pilotLatitude, isNull);
    expect(store.pilotLongitude, isNull);
    expect(store.pilotLastSeen, isNull);
  });
}
