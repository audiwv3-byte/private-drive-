import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  test('Each stop is retained and restored independently', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас', paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 22), services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);

    final first = DateTime(2026, 11, 22, 9);
    expect(store.togglePause(now: first), isTrue);
    expect(store.currentStopElapsed(now: first.add(const Duration(minutes: 4))),
        const Duration(minutes: 4));
    expect(store.togglePause(now: first.add(const Duration(minutes: 5))), isTrue);
    expect(store.completedStopWaits, [const Duration(minutes: 5)]);

    final second = first.add(const Duration(minutes: 15));
    expect(store.togglePause(now: second), isTrue);
    final saved = store.toPersistedJson()!;
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(saved), isTrue);
    expect(restored.paused, isTrue);
    expect(restored.completedStopWaits, [const Duration(minutes: 5)]);
    expect(restored.currentStopElapsed(now: second.add(const Duration(minutes: 3))),
        const Duration(minutes: 3));
    expect(restored.togglePause(now: second.add(const Duration(minutes: 3))), isTrue);
    expect(restored.completedStopWaits,
        [const Duration(minutes: 5), const Duration(minutes: 3)]);
    expect(restored.totalStopWaiting(), const Duration(minutes: 8));
    expect(restored.advancePilot(), isTrue);
    expect(restored.status, DemoTripStatus.finished);
  });
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
    expect(find.textContaining('без начисления за посадку'), findsOneWidget);
    expect(find.text('Продолжить'), findsOneWidget);
    // Show elapsed time only; do not invent a charge or hourly rate.
    await tester.tap(stop);
    await tester.pump();
    expect(store.paused, isFalse);
    expect(find.text('Остановка'), findsOneWidget);
  });
}
