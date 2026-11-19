import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  testWidgets('Stop starts visible waiting timer, Continue resumes trip',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас', paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 20), services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.status, DemoTripStatus.approaching);

    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      enableMapTiles: false, tripStore: store,
    )));
    final stop = find.byKey(const Key('pilot-pause-trip'));
    expect(stop, findsOneWidget);
    await tester.tap(stop);
    await tester.pump();
    expect(store.paused, isTrue);
    expect(find.byKey(const Key('pilot-paid-wait-timer')), findsOneWidget);
    expect(find.textContaining('Платное ожидание'), findsOneWidget);
    expect(find.text('Продолжить'), findsOneWidget);
    // Show elapsed time only; do not invent a charge or hourly rate.
    await tester.tap(stop);
    await tester.pump();
    expect(store.paused, isFalse);
    expect(find.text('Остановка'), findsOneWidget);
  });
}
