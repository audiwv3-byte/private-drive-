import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/pilot_sound_settings.dart';
import 'package:private_drive/pilot_offer_tone.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/pd_slide_to_confirm.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('Three original alert melodies differ and have valid WAV headers', () {
    final tones = [for (var i=0; i<3; i++) createPilotOfferTone(i)];
    for (final tone in tones) {
      expect(String.fromCharCodes(tone.sublist(0, 4)), 'RIFF');
      expect(String.fromCharCodes(tone.sublist(8, 12)), 'WAVE');
      expect(tone.length, greaterThan(16000));
    }
    expect(tones[0], isNot(equals(tones[1])));
    expect(tones[1], isNot(equals(tones[2])));
  });

  testWidgets('Pilot has sound settings in left drawer', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PilotDemo(enableMapTiles: false),
    ));
    await tester.tap(find.byKey(const Key('pilot-open-drawer')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-drawer-sounds')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-drawer-sounds')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-sounds-enabled')), findsOneWidget);
    for (var i=0; i<3; i++) {
      expect(find.byKey(Key('pilot-order-melody-$i')), findsOneWidget);
    }
  });

  testWidgets('Full slider requires thumb to reach far right edge',
      (tester) async {
    var confirmations = 0;
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: Center(child: SizedBox(width: 320,
        child: PdSlideToConfirm(label: 'Завершить',
          thumbKey: const Key('confirm-thumb'),
          onConfirmed: () => confirmations++))),
    )));
    await tester.tap(find.byKey(const Key('confirm-thumb')));
    await tester.pump();
    expect(confirmations, 0);
    await tester.drag(find.byKey(const Key('confirm-thumb')),
      const Offset(110, 0));
    await tester.pumpAndSettle();
    expect(confirmations, 0);
    await tester.drag(find.byKey(const Key('confirm-thumb')),
      const Offset(270, 0));
    await tester.pumpAndSettle();
    expect(confirmations, 1);
  });
}
