import 'package:flutter/material.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/passenger_demo.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:private_drive/company_info.dart';
import 'package:private_drive/main.dart';

void main() {
  for (final pilot in [true, false]) {
    testWidgets('QA blocks ${pilot ? "Waze" : "Paysera"} launcher', (tester) async {
      expect(const bool.fromEnvironment('PD_ISOLATED_DEVICE_QA'), isTrue);
      var launches = 0;
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      const channel = MethodChannel('plugins.flutter.io/url_launcher');
      messenger.setMockMethodCallHandler(channel, (call) async {
        launches++;
        return true;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
      await tester.pumpWidget(MaterialApp(home: pilot
          ? const PilotDemo(enableMapTiles: false)
          : const PassengerDemo(enableMapTiles: false)));
      final finder = find.byKey(Key(pilot ? 'pilot-open-waze' : 'passenger-paysera-info'));
      if (!pilot) {
        await tester.scrollUntilVisible(finder, 250, maxScrolls: 100,
            scrollable: find.byType(Scrollable).first);
      }
      expect(finder, findsOneWidget);
      await tester.ensureVisible(finder);
      await tester.tap(finder);
      await tester.pump();
      expect(launches, 0);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('QA blocks company external link before invoking launcher', (tester) async {
    expect(const bool.fromEnvironment('PD_ISOLATED_DEVICE_QA'), isTrue);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: Builder(
      builder: (context) => TextButton(
        onPressed: () => openPrivateDriveLink(context, Uri.parse('https://example.invalid')),
        child: const Text('External link'),
      ),
    ))));
    await tester.tap(find.text('External link'));
    await tester.pump();
    expect(find.text('Внешние ссылки отключены в изолированной QA-сборке.'), findsOneWidget);
  });

  testWidgets('QA blocks Telegram before HTTP and external launcher', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1050);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var requests = 0;
    var launches = 0;
    final client = MockClient((request) async {
      requests++;
      throw StateError('Unexpected network request');
    });
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
      authApiUrl: 'https://example.invalid',
      httpClient: client,
      telegramLauncher: (_) async { launches++; return true; },
    )));
    final legal = find.byKey(const Key('native-legal-acknowledgement'));
    await tester.scrollUntilVisible(legal, 100, scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(legal);
    await tester.tap(legal);
    await tester.pumpAndSettle();
    final start = find.byKey(const Key('native-telegram-start'));
    await tester.scrollUntilVisible(start, 100, scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(start);
    await tester.tap(start);
    await tester.pumpAndSettle();
    expect(requests, 0);
    expect(launches, 0);
  });
}
