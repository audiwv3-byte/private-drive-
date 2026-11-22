import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/pilot_cabin.dart';
import 'package:private_drive/pilot_identity_notice_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('Local test PIN opens cabins without a native session', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(MaterialApp(home: PdNativeCabinEntry(
      signInBuilder: (_, _, _) => throw StateError('No server sign-in expected'),
      identityApiBuilder: (_) => throw StateError('No identity API expected'),
    )));
    await tester.pumpAndSettle();

    final pin = find.byKey(const Key('local-qa-pin'));
    final enter = find.byKey(const Key('local-qa-enter'));
    if (!pdLocalQaEntryEnabled) {
      expect(pin, findsNothing);
      expect(find.byKey(const Key('entry-cabin-selection')), findsOneWidget);
      return;
    }

    Future<void> tap(Finder finder) async {
      await tester.ensureVisible(finder);
      await tester.tap(finder);
      await tester.pumpAndSettle();
    }

    expect(find.byKey(const Key('entry-pilot')), findsNothing);
    await tester.enterText(pin, '000000');
    await tap(enter);
    expect(find.text('Неверный тестовый пароль'), findsOneWidget);
    expect(find.byKey(const Key('entry-dispatcher')), findsNothing);
    await tester.enterText(pin, const String.fromEnvironment('PD_QA_LOCAL_PIN'));
    await tap(enter);

    expect(find.byKey(const Key('entry-dispatcher')), findsNothing);
    for (final role in const ['passenger', 'pilot']) {
      await tap(find.byKey(Key('entry-$role')));
      expect(find.byKey(const Key('local-qa-status')), findsOneWidget);
      expect(find.byType(PdPilotIdentityNoticePage), findsNothing);
      expect(find.byKey(const Key('pilot-open-identity-check')), findsNothing);
      expect(find.byKey(const Key('dispatcher-photo-review')), findsNothing);
      if (role == 'passenger') {
        expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
      } else {
        expect(find.byType(PilotCabin), findsOneWidget);
      }
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
    }

    await tap(find.byTooltip('Выйти'));
    expect(pin, findsOneWidget);
  });
}
