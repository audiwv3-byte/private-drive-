import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/main.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('synthetic Safari login stays in the authenticated passenger cabin',
      (tester) async {
    if (!const bool.fromEnvironment('PD_ISOLATED_QA_AUTH')) return;
    await tester.binding.setSurfaceSize(const Size(430, 940));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    SharedPreferences.setMockInitialValues({});
    var sessions = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/native-auth/qa-session') {
        expect(request.method, 'POST');
        expect(jsonDecode(request.body)['role'], 'passenger');
        sessions++;
        return http.Response(jsonEncode({
          'verified': false,
          'qa': true,
          'role': 'passenger',
          'token_type': 'Bearer',
          'access_token': 'a' * 64,
          'user_id': 'passenger-qa',
          'expires_in': 3600,
        }), 200, headers: {'content-type': 'application/json'});
      }
      if (request.url.path == '/v1/me') {
        expect(request.headers['Authorization'], 'Bearer ${'a' * 64}');
        return http.Response('{"role":"passenger","user_id":"passenger-qa"}', 200);
      }
      if (request.url.path == '/v1/current') {
        return http.Response('{"trip":null,"gps":null}', 200);
      }
      return http.Response('{"error":"not_found"}', 404);
    });
    addTearDown(client.close);
    await tester.pumpWidget(PrivateDriveApp(
      mockApiUrl: 'https://qa.invalid', httpClient: client, enableMapTiles: false));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('entry-passenger')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('native-legal-acknowledgement')), 180,
      scrollable: find.byType(Scrollable).last);
    await tester.ensureVisible(find.byKey(const Key('native-legal-acknowledgement')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('native-legal-acknowledgement')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('qa-sign-in')), 180,
      scrollable: find.byType(Scrollable).last);
    await tester.ensureVisible(find.byKey(const Key('qa-sign-in')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('qa-sign-in')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pumpAndSettle();
    expect(sessions, 1);
    expect(find.byKey(const Key('entry-cabin-selection')), findsNothing);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    // Reopening the role chooser must preserve the live bearer session.
    await tester.tap(find.byType(BackButton).first);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
    await tester.tap(find.byKey(const Key('entry-passenger')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(sessions, 1);
    // Simulate a Safari Flutter page restart without resetting browser storage.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.pumpWidget(PrivateDriveApp(
      mockApiUrl: 'https://qa.invalid', httpClient: client, enableMapTiles: false));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(sessions, 1);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
