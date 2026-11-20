import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/pilot_cabin.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/brand_logo.dart';

void main() {
  // These tests cover sign-in, not the separately tested first-run prompts.
  setUp(() => SharedPreferences.setMockInitialValues({
    'pd_native_permissions_onboarding_v1': true,
  }));
  testWidgets('Approved PD logo and upgraded version are visible on startup',
      (tester) async {
    final asset = await rootBundle.load(privateDriveLogoAsset);
    final bytes = asset.buffer.asUint8List();
    expect(bytes.length, greaterThan(1000000),
        reason: 'Lossless official 1254px logo must not be downsampled.');
    expect(String.fromCharCodes(bytes.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(bytes.sublist(8, 12)), 'WEBP');
    expect(String.fromCharCodes(bytes.sublist(12, 16)), 'VP8L');
    final width = 1 + ((bytes[21] | (bytes[22] << 8)) & 0x3fff);
    final height = 1 +
        (((bytes[22] >> 6) | (bytes[23] << 2) | (bytes[24] << 10)) & 0x3fff);
    expect(width, 1254);
    expect(height, 1254);

    await tester.pumpWidget(const PrivateDriveApp());
    await tester.pumpAndSettle();
    expect(find.byType(PrivateDriveBrandLogo), findsOneWidget);
    expect(find.byKey(const Key('private-drive-brand-logo')), findsOneWidget);
    expect(find.textContaining('0.2.24'), findsOneWidget);
    expect(find.textContaining('2026112022'), findsOneWidget);
    expect(find.byIcon(Icons.local_taxi_outlined), findsNothing);
  });

  testWidgets('Offline preview blocks real OTP requests', (tester) async {
    expect(apiBaseUrl, isEmpty,
        reason: 'Unsigned CI must not connect to production or paid SMS.');
    await tester.pumpWidget(const PrivateDriveApp());
    await tester.pumpAndSettle();

    expect(find.text('PRIVATE DRIVE'), findsWidgets);
    expect(find.text('Независимый вход без Telegram'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Получить код'), 120,
      scrollable: find.byType(Scrollable).first);
    expect(find.text('Получить код'), findsOneWidget);
    expect(find.byKey(const Key('open-offline-demo')), findsNothing);

    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Получить код'),
    );
    expect(button.onPressed, isNull,
        reason: 'No network request must be possible without a test API.');
    // The explanatory banner is below the fold on compact Android screens.
    await tester.scrollUntilVisible(
      find.textContaining('сервер авторизации не подключён'),
      160,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('сервер авторизации не подключён'), findsOneWidget);
  });

  testWidgets('Only phone sign-in is offered and no OTP is sent offline',
      (tester) async {
    await tester.pumpWidget(const PrivateDriveApp());
    await tester.pumpAndSettle();
    expect(find.text('Телефон в формате +370...'), findsOneWidget);
    expect(find.text('Email'), findsNothing);
    expect(find.byType(SegmentedButton<bool>), findsNothing);
    await tester.scrollUntilVisible(find.text('Получить код'), 120,
      scrollable: find.byType(Scrollable).first);
    expect(find.text('Получить код'), findsOneWidget);
    expect(tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Получить код'),
    ).onPressed, isNull);
  });
  testWidgets('Server-authorized admin shell shows dispatcher, not passenger or pilot',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PrivateDriveDemo(adminOnly: true, enableMapTiles: false),
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsNothing);
    expect(find.byKey(const Key('open-pilot-preview')), findsNothing);
    expect(find.byKey(const Key('open-passenger-preview')), findsNothing);
  });

  testWidgets('Public SMS passenger shell never exposes pilot or dispatcher roles',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PrivateDriveDemo(passengerOnly: true, enableMapTiles: false),
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-transfer')), findsOneWidget);
    expect(find.byKey(const Key('open-pilot-preview')), findsNothing);
    expect(find.byKey(const Key('open-dispatcher-preview')), findsNothing);
    expect(find.byKey(const Key('open-remote-sync-demo')), findsNothing);
  });

  for (final role in ['passenger', 'pilot', 'dispatcher', 'pilot_dispatcher']) {
    testWidgets('Verified server role opens the authorized cabin: $role',
        (tester) async {
      final client = MockClient((request) async {
        final payload = jsonDecode(request.body) as Map<String, dynamic>;
        expect(payload.containsKey('role'), isFalse);
        if (request.url.path.endsWith('/request-code')) {
          return http.Response('{"challenge_id":"synthetic"}', 202);
        }
        expect(request.url.path, '/native-auth/verify-code');
        expect(payload['code'], '123456');
        return http.Response(jsonEncode({
          'verified': true,
          'access_token': List.filled(48, 'x').join(),
          'user_id': 'synthetic-account',
          'token_type': 'Bearer',
          'expires_in': 60,
          'role': role,
        }), 200);
      });
      addTearDown(client.close);
      tester.view.physicalSize = const Size(800, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(
        home: NativeSignInScreen(authApiUrl: 'https://example.test', httpClient: client),
      ));
      await tester.enterText(find.byType(TextField).first, '+37060000000');
      final legal = find.byKey(const Key('native-legal-acknowledgement'));
      await tester.ensureVisible(legal);
      await tester.tap(legal);
      await tester.pumpAndSettle();
      final requestCode = find.text('Получить код');
      await tester.scrollUntilVisible(requestCode, 120,
          scrollable: find.byType(Scrollable).first);
      expect(tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Получить код'),
      ).onPressed, isNotNull);
      await tester.tap(requestCode);
      await tester.pumpAndSettle();
      final otp = find.widgetWithText(TextField, 'Код подтверждения');
      expect(otp, findsOneWidget);
      await tester.enterText(otp, '123456');
      await tester.pumpAndSettle();
      final verify = find.text('Подтвердить');
      await tester.scrollUntilVisible(verify, 120,
          scrollable: find.byType(Scrollable).first);
      await tester.tap(verify);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('native-account-verified')), findsOneWidget);
      expect(find.byKey(const Key('native-verified-user-id')), findsOneWidget);
      expect(find.text('synthetic-account'), findsOneWidget);
      expect(find.byKey(const Key('native-copy-user-id')), findsOneWidget);
      expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
      expect(find.byType(PilotCabin), findsNothing);
      await tester.tap(find.byKey(const Key('native-continue-to-cabin')));
      await tester.pumpAndSettle();

      final pilot = find.byKey(const Key('authorized-open-pilot'));
      final dispatcher = find.byKey(const Key('authorized-open-dispatcher'));
      final dispatcherDrawer = find.byKey(const Key('dispatcher-open-drawer'));
      if (role == 'pilot_dispatcher') {
        await tester.tap(pilot);
        await tester.pumpAndSettle();
        expect(find.byType(PilotCabin), findsOneWidget);
        expect(dispatcherDrawer, findsNothing);
        await tester.tap(find.byType(BackButton));
        await tester.pumpAndSettle();
        await tester.tap(dispatcher);
        await tester.pumpAndSettle();
        expect(dispatcherDrawer, findsOneWidget);
      } else {
        expect(pilot, findsNothing);
        expect(dispatcher, findsNothing);
        expect(find.byType(PilotCabin),
            role == 'pilot' ? findsOneWidget : findsNothing);
        expect(dispatcherDrawer,
            role == 'dispatcher' ? findsOneWidget : findsNothing);
      }
      expect(find.byKey(const Key('passenger-entry-taxi')),
          role == 'passenger' ? findsOneWidget : findsNothing);
      expect(find.byKey(const Key('open-offline-demo')), findsNothing);
    });
  }

}
