import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/brand_logo.dart';

void main() {
  testWidgets('Approved PD logo and upgraded version are visible on startup',
      (tester) async {
    final bytes = base64Decode(privateDriveLogoBase64);
    expect(bytes.length, greaterThan(3000));
    expect(String.fromCharCodes(bytes.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(bytes.sublist(8, 12)), 'WEBP');

    await tester.pumpWidget(const PrivateDriveApp());
    expect(find.byType(PrivateDriveBrandLogo), findsOneWidget);
    expect(find.byKey(const Key('private-drive-brand-logo')), findsOneWidget);
    expect(find.textContaining('0.2.0'), findsOneWidget);
    expect(find.textContaining('20261118'), findsOneWidget);
    expect(find.byIcon(Icons.local_taxi_outlined), findsNothing);
  });

  testWidgets('Offline preview blocks real OTP requests', (tester) async {
    expect(apiBaseUrl, isEmpty,
        reason: 'Unsigned CI must not connect to production or paid SMS.');
    await tester.pumpWidget(const PrivateDriveApp());

    expect(find.text('PRIVATE DRIVE'), findsWidgets);
    expect(find.text('Независимый вход без Telegram'), findsOneWidget);
    expect(find.text('Получить код'), findsOneWidget);
    expect(find.textContaining('сервер авторизации не подключён'), findsOneWidget);

    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Получить код'),
    );
    expect(button.onPressed, isNull,
        reason: 'No network request must be possible without a test API.');
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
