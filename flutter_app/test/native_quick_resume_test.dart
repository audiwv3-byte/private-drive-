import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_session_manager.dart';
import 'package:private_drive/native_session_vault.dart';
import 'package:private_drive/pilot_identity_api.dart';
import 'package:private_drive/pilot_identity_notice_page.dart';
import 'package:private_drive/pilot_cabin.dart';

class VerifiedRestoredSession extends PdNativeSessionManager {
  VerifiedRestoredSession(this.restored)
      : super(baseUrl: 'https://example.invalid',
          vault: const PdNativeSessionVault());

  final PdNativeSession restored;

  @override
  Future<PdNativeSession?> restore() async => restored;
}

PdNativeSession session(String role) => PdNativeSession(
  token: 'synthetic-only-server-verified-token-not-usable-outside-tests',
  userId: 'qa-user', role: role,
  expiresAt: DateTime.now().add(const Duration(minutes: 20)),
);

Widget app(String role, {required bool quickResume}) => MaterialApp(
  home: PdNativeCabinEntry(
    quickResume: quickResume,
    sessionManager: VerifiedRestoredSession(session(role)),
    identityApiBuilder: (s) => PdIdentityApi(
      baseUrl: 'https://example.invalid', token: s.token),
    signInBuilder: (_, _, _) => const Text('Phone sign-in'),
  ),
);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('verified passenger resumes without phone or role screen',
      (tester) async {
    await tester.pumpWidget(app('passenger', quickResume: true));
    await tester.pumpAndSettle();
    expect(find.text('Phone sign-in'), findsNothing);
    expect(find.byKey(const Key('entry-cabin-selection')), findsNothing);
    expect(find.byKey(const Key('entry-passenger')), findsNothing);
  });

  testWidgets('verified pilot resumes only to photo approval gate',
      (tester) async {
    await tester.pumpWidget(app('pilot', quickResume: true));
    await tester.pumpAndSettle();
    expect(find.byType(PdPilotIdentityNoticePage), findsOneWidget);
    expect(find.byType(PilotCabin), findsNothing);
    expect(find.text('Phone sign-in'), findsNothing);
  });

  testWidgets('administrator never automatically enters a staff cabin',
      (tester) async {
    await tester.pumpWidget(app('admin', quickResume: true));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
    expect(find.byType(PilotCabin), findsNothing);
  });

  testWidgets('quick resume off keeps explicit selection unchanged',
      (tester) async {
    await tester.pumpWidget(app('passenger', quickResume: false));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
  });
}
