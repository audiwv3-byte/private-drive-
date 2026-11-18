import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/brand_logo.dart';

void main() {
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
    expect(find.byType(PrivateDriveBrandLogo), findsOneWidget);
    expect(find.byKey(const Key('private-drive-brand-logo')), findsOneWidget);
    expect(find.textContaining('0.2.5'), findsOneWidget);
    expect(find.textContaining('2026111805'), findsOneWidget);
    expect(find.byIcon(Icons.local_taxi_outlined), findsNothing);
  });

  testWidgets('Offline preview blocks real OTP requests', (tester) async {
    expect(apiBaseUrl, isEmpty,
        reason: 'Unsigned CI must not connect to production or paid SMS.');
    await tester.pumpWidget(const PrivateDriveApp());

    expect(find.text('PRIVATE DRIVE'), findsWidgets);
    expect(find.text('Независимый вход без Telegram'), findsOneWidget);
    expect(find.text('Получить код'), findsOneWidget);

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

  testWidgets('Phone and email switch without sending OTP', (tester) async {
    await tester.pumpWidget(const PrivateDriveApp());
    expect(find.text('Телефон в формате +370...'), findsOneWidget);

    await tester.tap(find.text('Email'));
    await tester.pump();

    expect(find.text('Email'), findsWidgets);
    expect(find.text('Телефон в формате +370...'), findsNothing);
    expect(find.text('Получить код'), findsOneWidget);
    expect(
      tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Получить код'),
      ).onPressed,
      isNull,
    );
  });
}
