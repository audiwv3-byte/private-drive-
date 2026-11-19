import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';

void main() {
  testWidgets('Pilot trip panel collapses and expands without hiding map',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: PilotDemo(
      enableMapTiles: false,
    )));
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.byKey(const Key('pilot-next-trip')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-trip-panel-toggle')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.byKey(const Key('pilot-next-trip')), findsNothing);
    await tester.tap(find.byKey(const Key('pilot-trip-panel-toggle')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-next-trip')), findsOneWidget);
  });
}
