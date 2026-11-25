import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/pilot_identity_api.dart';
import 'package:private_drive/pilot_identity_notice_page.dart';
import 'package:private_drive/pilot_cabin.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> tap(WidgetTester tester, String key) async {
    final finder = find.byKey(Key(key));
    if (finder.evaluate().isEmpty) {
      await tester.scrollUntilVisible(finder, 180,
        scrollable: find.byType(Scrollable).last);
    }
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }
  Future<void> pumpEntry(WidgetTester tester, {String serverRole = 'passenger',
      bool photoRequested = false}) async {
    final client = MockClient((request) async => http.Response(
      '{"status":"unverified","requested":$photoRequested}', 200));
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: PdNativeCabinEntry(
      signInBuilder: (_, role, authenticated) => Scaffold(
        body: Column(children: [Text('Sign in $role', key: const Key('entry-test-sign-in')),
          FilledButton(key: const Key('entry-test-authenticate'),
            onPressed: () => authenticated(PdNativeSession(token: 'synthetic-token', userId: 'synthetic-id',
              role: serverRole, expiresAt: DateTime.now().add(const Duration(minutes: 1)))),
            child: const Text('Authenticate synthetic account')),
        ])),
      identityApiBuilder: (session) => PdIdentityApi(baseUrl: 'https://example.test',
        token: session.token, client: client),
    )));
    await tester.pumpAndSettle();
    addTearDown(() => tester.pumpWidget(const SizedBox.shrink()));
  }
  Future<void> skipPermissions(WidgetTester tester) async {
    final skip = find.byKey(const Key('permission-onboarding-skip'));
    if (skip.evaluate().isNotEmpty) await tap(tester, 'permission-onboarding-skip');
  }

  testWidgets('first screen shows passenger and pilot before phone or photo', (tester) async {
    await pumpEntry(tester);
    for (final role in ['passenger', 'pilot']) {
      expect(find.byKey(Key('entry-$role')), findsOneWidget);
    }
    expect(find.byKey(const Key('entry-dispatcher')), findsNothing);
    expect(find.byKey(const Key('entry-test-sign-in')), findsNothing);
    expect(find.byType(PdPilotIdentityNoticePage), findsNothing);
  });

  testWidgets('pilot selection opens sign-in directly without a photo prompt', (tester) async {
    await pumpEntry(tester);
    await tap(tester, 'entry-pilot');
    expect(find.byType(PdPilotIdentityNoticePage), findsNothing);
    expect(find.byType(PilotCabin), findsNothing);
    expect(find.byKey(const Key('entry-test-sign-in')), findsOneWidget);
    await tester.tap(find.byType(BackButton).first);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
  });

  testWidgets('passenger never sees photo and guest never receives staff rights', (tester) async {
    await pumpEntry(tester);
    await tap(tester, 'entry-passenger');
    if (!const bool.fromEnvironment('PD_INTERNAL_QA')) await tap(tester, 'entry-test-authenticate');
    await skipPermissions(tester);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(find.byType(PdPilotIdentityNoticePage), findsNothing);
    expect(find.byType(PilotCabin), findsNothing);
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
  });

  testWidgets('a dispatcher account does not unlock the native pilot cabin', (tester) async {
    await pumpEntry(tester, serverRole: 'dispatcher');
    await tap(tester, 'entry-pilot');
    await tap(tester, 'entry-test-authenticate');
    expect(find.byKey(const Key('entry-role-message')), findsOneWidget);
    expect(find.byType(PilotCabin), findsNothing);
    expect(find.byKey(const Key('entry-dispatcher')), findsOneWidget);
  });

  testWidgets('pilot cabin opens before photo approval', (tester) async {
    await pumpEntry(tester, serverRole: 'pilot');
    await tap(tester, 'entry-pilot');
    await tap(tester, 'entry-test-authenticate');
    await skipPermissions(tester);
    expect(find.byType(PilotCabin), findsOneWidget);
    expect(find.byType(PdPilotIdentityNoticePage), findsNothing);
    expect(find.byKey(const Key('pilot-open-identity-check')), findsNothing);
  });

  testWidgets('dispatcher request shows an optional photo action inside the cabin', (tester) async {
    await pumpEntry(tester, serverRole: 'pilot', photoRequested: true);
    await tap(tester, 'entry-pilot');
    await tap(tester, 'entry-test-authenticate');
    await skipPermissions(tester);
    expect(find.byType(PilotCabin), findsOneWidget);
    expect(find.byType(PdPilotIdentityNoticePage), findsNothing);
    await tap(tester, 'pilot-open-identity-check');
    expect(find.byType(PdPilotIdentityNoticePage), findsOneWidget);
  });
}
