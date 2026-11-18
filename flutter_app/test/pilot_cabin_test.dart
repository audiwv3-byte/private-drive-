import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/pilot_cabin.dart';

void main() {
  testWidgets('Pilot POWER starts red in cabin, opens map, and turns green',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: PilotCabin(enableMapTiles: false)),
    );

    expect(find.byKey(const Key('pilot-power-toggle')), findsOneWidget);
    expect(find.text('Не на линии · демо'), findsOneWidget);
    expect(find.text('ВЫЙТИ НА ЛИНИЮ'), findsOneWidget);
    expect(find.byKey(const Key('pilot-offline-vilnius-background')), findsOneWidget);
    expect(find.byKey(const Key('pilot-map-surface')), findsNothing);

    final powerOffIcon = tester.widget<Icon>(
      find.byIcon(Icons.power_settings_new),
    );
    expect(powerOffIcon.color, const Color(0xFFFC4654));

    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pumpAndSettle();

    expect(find.byType(PilotDemo), findsOneWidget);
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.byKey(const Key('pilot-offline-vilnius-background')), findsNothing);
    // The POWER button lives in the cabin, not in any map overlay.
    expect(find.byKey(const Key('pilot-power-toggle')), findsNothing);
    expect(find.text('Администратор'), findsNothing);
    expect(find.text('Пассажир'), findsNothing);

    await tester.tap(find.byKey(const Key('exit-pilot-preview')));
    await tester.pumpAndSettle();

    expect(find.text('На линии · демо'), findsOneWidget);
    expect(find.byKey(const Key('pilot-offline-vilnius-background')), findsNothing);
    expect(find.text('УЙТИ С ЛИНИИ'), findsOneWidget);
    expect(find.byKey(const Key('pilot-open-map')), findsOneWidget);
    final powerOnIcon = tester.widget<Icon>(
      find.byIcon(Icons.power_settings_new),
    );
    expect(powerOnIcon.color, const Color(0xFF34E88A));

    await tester.tap(find.byKey(const Key('pilot-open-map')));
    await tester.pumpAndSettle();
    expect(find.byType(PilotDemo), findsOneWidget);
    await tester.tap(find.byKey(const Key('exit-pilot-preview')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pump();
    expect(find.text('Не на линии · демо'), findsOneWidget);
    expect(find.byKey(const Key('pilot-offline-vilnius-background')), findsOneWidget);
    expect(find.byKey(const Key('pilot-open-map')), findsNothing);
    expect(tester.widget<Icon>(
      find.byIcon(Icons.power_settings_new),
    ).color, const Color(0xFFFC4654));
  });
}
