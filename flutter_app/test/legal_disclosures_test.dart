import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/company_info.dart';
import 'package:private_drive/main.dart';

void main() {
  testWidgets('SMS entry shows privacy and terms without marketing opt-in',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NativeSignInScreen()));
    expect(find.byKey(const Key('native-legal-acknowledgement')),
        findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('native-open-legal-documents')), 120,
      scrollable: find.byType(Scrollable).first);
    await tester.tap(find.byKey(const Key('native-open-legal-documents')));
    await tester.pumpAndSettle();
    expect(find.text('Конфиденциальность'), findsOneWidget);
    expect(find.text('Отмена и возврат'), findsOneWidget);
  });

  testWidgets('Legal disclosures expose all four sections in app',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: CompanyInfoPage()));
    expect(find.byKey(const Key('company-contacts-tab')), findsOneWidget);
    expect(find.text('Соглашение'), findsOneWidget);
    expect(find.text('Конфиденциальность'), findsOneWidget);
    expect(find.text('Отмена и возврат'), findsOneWidget);
    await tester.tap(find.text('Конфиденциальность'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('company-privacy-tab')), findsOneWidget);
    expect(find.textContaining('GDPR'), findsWidgets);
    await tester.tap(find.text('Отмена и возврат'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('company-refunds-tab')), findsOneWidget);
    expect(find.textContaining('пяти минут'), findsWidgets);
  });
}
