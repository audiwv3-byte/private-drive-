import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pilot_cockpit_overlay.dart';
import 'package:private_drive/pilot_statistics_page.dart';

void main() {
  const cases = <(String, PilotStatisticSection)>[
    ('pilot-stat-income', PilotStatisticSection.income),
    ('pilot-stat-acceptance', PilotStatisticSection.acceptance),
    ('pilot-stat-rating', PilotStatisticSection.rating),
    ('pilot-stat-level', PilotStatisticSection.level),
    ('pilot-stat-rewards', PilotStatisticSection.rewards),
  ];

  for (final (tile, section) in cases) {
    testWidgets('pilot cockpit $tile opens and returns to map',
        (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Center(
            child: const Text('Карта пилота'),
          ),
        ),
      ));

      final overlayState = tester.state<OverlayState>(
        find.byType(Overlay).first,
      );
      final entry = OverlayEntry(
        builder: (_) => PilotCockpitOverlay(
          tripStore: null,
          onAccept: () {},
          onDecline: () {},
        ),
      );
      overlayState.insert(entry);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(
        const Key('pilot-cockpit-earnings-toggle')));
      await tester.pumpAndSettle();
      expect(find.byKey(Key(tile)), findsOneWidget);

      await tester.tap(find.byKey(Key(tile)));
      await tester.pumpAndSettle();

      expect(
        find.byKey(Key('pilot-statistics-page-${section.name}')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('pilot-statistics-no-data')),
        findsOneWidget);
      // The root overlay must not cover the new fullscreen route.
      expect(find.byKey(Key(tile)), findsNothing);

      await tester.tap(find.byKey(
        const Key('pilot-statistics-back')));
      await tester.pumpAndSettle();

      expect(find.text('Карта пилота'), findsOneWidget);
      expect(find.byKey(Key(tile)), findsOneWidget);
      entry.remove();
      entry.dispose();
      await tester.pump();
    });
  }
}
