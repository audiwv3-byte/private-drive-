import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/camera_test_main.dart';

void main() {
  testWidgets('isolated APK starts on no-auth camera test pilot home',
      (tester) async {
    await tester.pumpWidget(const PdIsolatedCameraTestApp());

    expect(find.byKey(const Key('isolated-camera-pilot-home')), findsOneWidget);
    expect(find.byKey(const Key('isolated-camera-open-identity')), findsOneWidget);
    expect(find.byKey(const Key('isolated-camera-safety-explanation')), findsOneWidget);
    expect(find.textContaining('Телефон в формате'), findsNothing);
    expect(find.textContaining('Получить код'), findsNothing);
    expect(find.textContaining('В этой сборке сервер авторизации'), findsNothing);
    expect(find.textContaining('администратора и серверная авторизация'),
        findsOneWidget);

    await tester.tap(find.byKey(const Key('isolated-camera-open-identity')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-identity-notice-page')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-check-page')), findsNothing);
    await tester.drag(find.byType(ListView).last, const Offset(0, -1200));
    await tester.pumpAndSettle();
    final proceed = tester.widget<FilledButton>(
      find.byKey(const Key('pilot-identity-notice-continue')),
    );
    expect(proceed.onPressed, isNull);
    await tester.drag(find.byType(ListView).last, const Offset(0, -1200));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('pilot-identity-notice-acknowledge')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('pilot-identity-notice-continue')));
    await tester.tap(find.byKey(const Key('pilot-identity-notice-continue')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-identity-check-page')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-request-camera')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-unverified-status')), findsOneWidget);
  });
}
