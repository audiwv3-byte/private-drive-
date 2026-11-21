import 'dart:typed_data';
import 'package:private_drive/pilot_photo_capture.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pilot_identity_notice_page.dart';
import 'package:private_drive/pilot_identity_check_page.dart';

class RecordingCamera implements PdPilotCameraPermission {
  int requests = 0;

  @override
  Future<bool> requestCamera() async {
    requests++;
    return true;
  }
}

class CancelledPhoto implements PdPilotPhotoCapture {
  @override
  Future<Uint8List?> capture() async => null;
}

void main() {
  testWidgets('Internal QA can exit notice without camera or granting identity',
      (tester) async {
    final camera = RecordingCamera();
    var returnedToCabinets = false;
    await tester.pumpWidget(MaterialApp(home: PdPilotIdentityNoticePage(
      cameraPermission: camera, photoCapture: CancelledPhoto(),
      onContinueWithoutVerification: () => returnedToCabinets = true,
    )));
    final skip = find.byKey(const Key('pilot-identity-notice-qa-skip'));
    if (const bool.fromEnvironment('PD_INTERNAL_QA')) {
      await tester.ensureVisible(skip);
      expect(skip, findsOneWidget);
      await tester.tap(skip);
      await tester.pumpAndSettle();
      expect(returnedToCabinets, isTrue);
      expect(camera.requests, 0);
      expect(find.textContaining('Личность не подтверждена'), findsOneWidget);
    } else {
      expect(skip, findsNothing);
      expect(returnedToCabinets, isFalse);
    }
  });
  testWidgets('RU notice requires acknowledgement before camera permission',
      (tester) async {
    final camera = RecordingCamera();
    await tester.pumpWidget(MaterialApp(
      home: PdPilotIdentityNoticePage(cameraPermission: camera, photoCapture: CancelledPhoto()),
    ));
    expect(find.textContaining('Проверка личности пилота'), findsOneWidget);
    expect(find.textContaining('Фото'), findsWidgets);
    expect(find.byKey(const Key('pilot-identity-notice-purpose')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-notice-retention')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-notice-rights')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-notice-contact')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-request-camera')), findsNothing);
    expect(camera.requests, 0);
    await tester.drag(find.byType(ListView).last, const Offset(0, -1200));
    await tester.pumpAndSettle();
    final disabled = tester.widget<FilledButton>(
      find.byKey(const Key('pilot-identity-notice-continue')),
    );
    expect(disabled.onPressed, isNull);

    await tester.drag(find.byType(ListView).last, const Offset(0, -1200));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('pilot-identity-notice-acknowledge')));
    await tester.pumpAndSettle();
    expect(camera.requests, 0);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('pilot-identity-notice-continue')),
    ).onPressed, isNotNull);
    await tester.ensureVisible(find.byKey(const Key('pilot-identity-notice-continue')));
    await tester.tap(find.byKey(const Key('pilot-identity-notice-continue')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-identity-check-page')), findsOneWidget);
    expect(camera.requests, 0);
    await tester.ensureVisible(find.byKey(const Key('pilot-identity-request-camera')));
    await tester.tap(find.byKey(const Key('pilot-identity-request-camera')));
    await tester.pumpAndSettle();
    expect(camera.requests, 1);
    expect(find.textContaining('Съёмка отменена'), findsOneWidget);
  });

  for (final language in ['LT', 'EN']) {
    testWidgets('$language notice is translated and resets acknowledgement',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: PdPilotIdentityNoticePage(),
      ));
      await tester.drag(find.byType(ListView).last, const Offset(0, -1200));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('pilot-identity-notice-acknowledge')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('pilot-identity-notice-language')));
      await tester.pumpAndSettle();
      await tester.tap(find.text(language).last);
      await tester.pumpAndSettle();

      expect(tester.widget<CheckboxListTile>(
        find.byKey(const Key('pilot-identity-notice-acknowledge')),
      ).value, isFalse);
      expect(tester.widget<FilledButton>(
        find.byKey(const Key('pilot-identity-notice-continue')),
      ).onPressed, isNull);
      expect(find.byKey(const Key('pilot-identity-request-camera')), findsNothing);

      await tester.drag(find.byType(ListView).last, const Offset(0, 1200));
      await tester.pumpAndSettle();
      expect(find.textContaining(language == 'LT'
          ? 'Vairuotojo tapatybės patikra'
          : 'Pilot identity verification'), findsOneWidget);
      expect(find.textContaining(language == 'LT'
          ? 'nuotrauk'
          : 'photo'), findsWidgets);
    });
  }
}
