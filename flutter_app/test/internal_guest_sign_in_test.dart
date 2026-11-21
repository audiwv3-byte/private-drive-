import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/pilot_cabin.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('guest entry is compiled only for internal QA', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NativeSignInScreen()));
    expect(find.byKey(const Key('internal-guest-entry')),
        const bool.fromEnvironment('PD_INTERNAL_QA') ? findsOneWidget : findsNothing);
  });

  testWidgets('internal guest opens passenger cabin with no OTP or staff privileges',
      (tester) async {
    if (!const bool.fromEnvironment('PD_INTERNAL_QA')) return;
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return http.Response('{"error":"sms_disabled"}', 503);
    });
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
      authApiUrl: 'https://example.test', httpClient: client)));
    await tester.ensureVisible(find.byKey(const Key('internal-guest-entry')));
    await tester.tap(find.byKey(const Key('internal-guest-entry')));
    await tester.pumpAndSettle();
    expect(calls, 0);
    expect(find.byKey(const Key('internal-guest-status')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-transfer')), findsOneWidget);
    expect(find.byKey(const Key('authorized-role-selection')), findsNothing);
    expect(find.byType(PilotCabin), findsNothing);
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
    expect(find.byKey(const Key('native-account-verified')), findsNothing);
    await tester.tap(find.byType(BackButton).first);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('internal-guest-entry')), findsOneWidget);
    expect(calls, 0);
  });

  for (final error in ['sms_disabled', 'invalid_phone', 'try_later']) {
    testWidgets('phone request displays actionable $error without a false code challenge',
        (tester) async {
      final client = MockClient((request) async => http.Response(
        jsonEncode({'error': error}), error == 'sms_disabled' ? 503 : error == 'try_later' ? 429 : 400));
      addTearDown(client.close);
      tester.view.physicalSize = const Size(800, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
        authApiUrl: 'https://example.test', httpClient: client)));
      await tester.enterText(find.byType(TextField).first, '+37060000000');
      final legal = find.byKey(const Key('native-legal-acknowledgement'));
      await tester.ensureVisible(legal);
      await tester.tap(legal);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Получить код'));
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();
      final expected = switch (error) {
        'sms_disabled' => 'Вход по SMS сейчас отключён',
        'invalid_phone' => 'Проверь номер:',
        _ => 'Слишком частые запросы.',
      };
      expect(find.textContaining(expected), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Код подтверждения'), findsNothing);
      expect(find.byKey(const Key('native-account-verified')), findsNothing);
    });
  }
}
