import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/pilot_cabin.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/brand_logo.dart';
import 'package:private_drive/app_language.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_session_store.dart';

Future<void> acceptFirstLaunchTerms(WidgetTester tester) async {
  final checkbox = find.byKey(const Key('first-launch-terms-acknowledgement'));
  final next = find.byKey(const Key('first-launch-continue'));
  expect(tester.widget<FilledButton>(next).onPressed, isNull);
  await tester.ensureVisible(checkbox);
  await tester.tap(checkbox);
  await tester.pumpAndSettle();
  await tester.ensureVisible(next);
  await tester.tap(next);
  await tester.pumpAndSettle();
}

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

    final language = PdLanguage();
    await tester.pumpWidget(PrivateDriveApp(language: language));
    await tester.pumpAndSettle();
    expect(find.byType(PrivateDriveBrandLogo), findsOneWidget);
    expect(find.byKey(const Key('private-drive-brand-logo')), findsOneWidget);
    if (!pdLocalQaEntryEnabled) {
      expect(find.byKey(const Key('private-drive-bright-auth-background')),
          findsOneWidget);
      for (final flag in ['🇷🇺 RU', '🇬🇧 EN', '🇱🇹 LT']) {
        expect(find.text(flag), findsOneWidget);
      }
      await tester.tap(find.byKey(const Key('first-language-RU')));
      await tester.pumpAndSettle();
      expect(language.hasSelection, isTrue);
      await acceptFirstLaunchTerms(tester);
    }
    expect(find.textContaining('0.2.27'), findsOneWidget);
    expect(find.textContaining('2026112103'), findsOneWidget);
    expect(find.byIcon(Icons.local_taxi_outlined), findsNothing);
  });

  testWidgets('First language selection localizes the passenger sign-in', (tester) async {
    final language = PdLanguage();
    await tester.pumpWidget(PrivateDriveApp(language: language));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('first-language-EN')));
    await tester.pumpAndSettle();
    expect(find.text('Choose your account'), findsNothing);
    expect(find.text('I have read the terms of service and privacy policy'),
        findsOneWidget);
    await acceptFirstLaunchTerms(tester);
    expect(language.hasAcknowledgedTerms, isTrue);
    expect(find.text('Choose your account'), findsOneWidget);

    await tester.tap(find.byKey(const Key('entry-passenger')));
    await tester.pumpAndSettle();
    expect(find.text('Passenger sign-in'), findsOneWidget);
    expect(find.byKey(const Key('native-legal-acknowledgement')), findsNothing);
    expect(find.text('Phone number +370...'), findsOneWidget);
  }, skip: pdLocalQaEntryEnabled || const bool.fromEnvironment('PD_INTERNAL_QA'));

  testWidgets('Offline preview blocks real OTP requests', (tester) async {
    expect(apiBaseUrl, isEmpty,
        reason: 'Unsigned CI must not connect to production or paid SMS.');
    await tester.pumpWidget(const MaterialApp(home: NativeSignInScreen()));
    await tester.pumpAndSettle();

    expect(find.text('PRIVATE DRIVE'), findsWidgets);
    expect(find.text('Войди через Telegram или SMS'), findsOneWidget);
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

  testWidgets('Both sign-in options stay offline without an API',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NativeSignInScreen()));
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
    final telegram = find.byKey(const Key('native-telegram-start'));
    await tester.scrollUntilVisible(telegram, 120,
      scrollable: find.byType(Scrollable).first);
    expect(tester.widget<OutlinedButton>(telegram).onPressed, isNull);
  });

  testWidgets('Telegram sign-in binds the browser code to the app attempt',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1050);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final state = List.filled(43, 's').join();
    final token = List.filled(64, 't').join();
    String? proof;
    PdNativeSession? authenticated;
    final client = MockClient((request) async {
      final data = jsonDecode(request.body) as Map<String, dynamic>;
      if (request.url.path.endsWith('/start')) {
        proof = data['app_secret'] as String;
        expect(proof, matches(r'^[A-Za-z0-9_-]{43}$'));
        expect(data['language'], 'RU');
        return http.Response(jsonEncode({
          'state': state,
          'authorization_url': 'https://oauth.telegram.org/auth?state=$state',
        }), 201);
      }
      expect(request.url.path, '/native-auth/telegram/finish');
      expect(data, {'state': state, 'app_secret': proof, 'code': '00123456'});
      return http.Response(jsonEncode({
        'verified': true, 'role': 'passenger', 'user_id': 'person-1',
        'access_token': token, 'token_type': 'Bearer', 'expires_in': 3600,
      }), 200);
    });
    await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
      authApiUrl: 'https://example.test',
      httpClient: client,
      onAuthenticated: (session) => authenticated = session,
      telegramLauncher: (uri) async {
        expect(uri.host, 'oauth.telegram.org');
        return true;
      },
    )));
    final start = find.byKey(const Key('native-telegram-start'));
    await tester.scrollUntilVisible(start, 100,
      scrollable: find.byType(Scrollable).first);
    await tester.tap(start);
    await tester.pumpAndSettle();
    expect(find.text('Отметь, что ознакомился с условиями, чтобы войти.'),
        findsOneWidget);
    expect(proof, isNull);

    final legal = find.byKey(const Key('native-legal-acknowledgement'));
    await tester.ensureVisible(legal);
    await tester.tap(legal);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(start, 100,
      scrollable: find.byType(Scrollable).first);
    await tester.tap(start);
    await tester.pumpAndSettle();
    final code = find.byKey(const Key('native-telegram-code'));
    await tester.scrollUntilVisible(code, 100,
      scrollable: find.byType(Scrollable).first);
    await tester.enterText(code, '00123456');
    await tester.pumpAndSettle();
    final finish = find.byKey(const Key('native-telegram-finish'));
    await tester.ensureVisible(finish);
    await tester.tap(finish);
    await tester.pumpAndSettle();
    expect(authenticated?.userId, 'person-1');
    expect(authenticated?.token, token);
  });

  testWidgets('Telegram approval completes automatically without a browser code',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1050);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final state = List.filled(43, 's').join();
    final token = List.filled(64, 't').join();
    String? proof;
    PdNativeSession? authenticated;
    var checks = 0;
    final client = MockClient((request) async {
      final data = jsonDecode(request.body) as Map<String, dynamic>;
      if (request.url.path.endsWith('/start')) {
        expect(data['mode'], 'automatic');
        proof = data['app_secret'] as String;
        return http.Response(jsonEncode({
          'state': state, 'automatic': true,
          'authorization_url': 'https://oauth.telegram.org/auth?state=$state',
        }), 201);
      }
      expect(request.url.path, '/native-auth/telegram/finish');
      expect(data, {'state': state, 'app_secret': proof});
      if (++checks == 1) return http.Response('{"pending":true}', 202);
      return http.Response(jsonEncode({
        'verified': true, 'role': 'pilot', 'user_id': 'pilot-1',
        'access_token': token, 'token_type': 'Bearer', 'expires_in': 3600,
      }), 200);
    });
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
      authApiUrl: 'https://example.test',
      legalAcknowledged: true,
      httpClient: client,
      onAuthenticated: (session) => authenticated = session,
      telegramLauncher: (_) async => true,
    )));
    final start = find.byKey(const Key('native-telegram-start'));
    await tester.scrollUntilVisible(start, 100,
      scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(start);
    await tester.pumpAndSettle();
    await tester.tap(start);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('native-telegram-code')), findsNothing);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(authenticated, isNull);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump();
    expect(authenticated?.userId, 'pilot-1');
    expect(authenticated?.token, token);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test('Saved session is validated, isolated by server and cleared on expiry', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final token = List.filled(64, 't').join();
    var expired = false;
    final client = MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer $token');
      expect(request.url.path, '/native-auth/session');
      if (expired) return http.Response('{"error":"invalid_session"}', 401);
      return http.Response(jsonEncode({
        'verified': true, 'role': 'passenger', 'user_id': 'person-1',
        'token_type': 'Bearer', 'expires_in': 3600,
      }), 200);
    });
    final store = PdNativeSessionStore('https://example.test', client: client);
    await store.save(PdNativeSession(
      token: token, userId: 'person-1', role: 'pilot',
      expiresAt: DateTime.now().add(const Duration(hours: 1)),
    ), 'pilot');
    expect(await PdNativeSessionStore('https://other.test', client: client).restore(), isNull);
    final restored = (await store.restore())!;
    expect(restored.$1.userId, 'person-1');
    expect(restored.$2, 'passenger');
    expired = true;
    expect(await store.restore(), isNull);
    expired = false;
    expect(await store.restore(), isNull);
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
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-transfer')), 180);
    expect(find.byKey(const Key('passenger-entry-transfer')), findsOneWidget);
    expect(find.byKey(const Key('open-pilot-preview')), findsNothing);
    expect(find.byKey(const Key('open-dispatcher-preview')), findsNothing);
    expect(find.byKey(const Key('open-remote-sync-demo')), findsNothing);
  });

  for (final role in ['passenger', 'pilot', 'dispatcher', 'pilot_dispatcher', 'admin']) {
    testWidgets('Verified $role chooses a cabin with server permissions',
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
      await tester.tap(requestCode);
      await tester.pumpAndSettle();
      final otp = find.widgetWithText(TextField, 'Код подтверждения');
      await tester.enterText(otp, '123456');
      await tester.pumpAndSettle();
      final verify = find.text('Подтвердить');
      await tester.scrollUntilVisible(verify, 120,
          scrollable: find.byType(Scrollable).first);
      await tester.tap(verify);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('native-account-verified')), findsOneWidget);
      await tester.tap(find.byKey(const Key('native-continue-to-cabin')));
      await tester.pumpAndSettle();

      final passenger = find.byKey(const Key('authorized-open-passenger'));
      final pilot = find.byKey(const Key('authorized-open-pilot'));
      final dispatcher = find.byKey(const Key('authorized-open-dispatcher'));
      expect(find.byKey(const Key('authorized-role-selection')), findsOneWidget);
      expect(passenger, findsOneWidget);
      expect(pilot, findsOneWidget);
      expect(dispatcher, findsNothing);
      expect(find.byType(PilotCabin), findsNothing);
      expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
      final pilotAllowed = ['pilot', 'pilot_dispatcher', 'admin'].contains(role);
      expect(tester.widget<FilledButton>(pilot).onPressed,
          pilotAllowed ? isNotNull : isNull);

      await tester.tap(passenger);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
      await tester.tap(find.byType(BackButton).first);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('authorized-role-selection')), findsOneWidget);

      if (pilotAllowed) {
        await tester.tap(pilot);
        await tester.pumpAndSettle();
        expect(find.byType(PilotCabin), findsOneWidget);
        expect(find.byKey(const Key('pilot-open-identity-check')), findsNothing);
        await tester.tap(find.byType(BackButton).first);
        await tester.pumpAndSettle();
      }
      expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
    });
  }

}

