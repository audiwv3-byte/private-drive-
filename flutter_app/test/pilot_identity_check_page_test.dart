import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pilot_identity_check_page.dart';

class FakeCamera implements PdPilotCameraPermission {
  FakeCamera({required this.granted});
  final bool granted;
  int requests = 0;

  @override
  Future<bool> requestCamera() async {
    requests++;
    return granted;
  }
}

void main() {
  testWidgets('QA skip is gated and never reports verified identity',
      (tester) async {
    var skipped = false;
    await tester.pumpWidget(MaterialApp(home:
      PdPilotIdentityCheckPage(
        cameraPermission: FakeCamera(granted: false),
        onContinueWithoutVerification: () => skipped = true,
      )));
    final skip = find.byKey(const Key('pilot-identity-qa-skip'));
    if (const bool.fromEnvironment('PD_INTERNAL_QA')) {
      expect(skip, findsOneWidget);
      await tester.tap(skip);
      await tester.pumpAndSettle();
      expect(skipped, isTrue);
      expect(find.byKey(const Key('pilot-identity-unverified-status')),
          findsOneWidget);
      expect(find.textContaining('Личность не подтверждена'), findsOneWidget);
    } else {
      expect(skip, findsNothing);
      expect(skipped, isFalse);
    }
  });
  testWidgets('does not request camera before the pilot explicitly taps',
      (tester) async {
    final camera = FakeCamera(granted: true);
    await tester.pumpWidget(MaterialApp(home:
        PdPilotIdentityCheckPage(cameraPermission: camera)));
    expect(find.byKey(const Key('pilot-identity-check-page')), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-unverified-status')),
        findsOneWidget);
    expect(camera.requests, 0);
    expect(find.textContaining('не создаётся, не сохраняется и не отправляется'),
        findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-identity-request-camera')));
    await tester.pumpAndSettle();
    expect(camera.requests, 1);
    expect(find.textContaining('Съёмка отключена'), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-unverified-status')),
        findsOneWidget);
  });

  testWidgets('denying camera keeps an honest unverified status',
      (tester) async {
    final camera = FakeCamera(granted: false);
    await tester.pumpWidget(MaterialApp(home:
        PdPilotIdentityCheckPage(cameraPermission: camera)));

    await tester.tap(find.byKey(const Key('pilot-identity-request-camera')));
    await tester.pumpAndSettle();

    expect(camera.requests, 1);
    expect(find.textContaining('не предоставлен'), findsOneWidget);
    expect(find.byKey(const Key('pilot-identity-unverified-status')),
        findsOneWidget);
  });
}
