import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/main.dart';

void main() {
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
