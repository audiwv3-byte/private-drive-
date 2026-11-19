import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  testWidgets('Pilot must swipe right, then can rate the completed passenger',
      (tester) async {
    final trip = DemoTripStore();
    addTearDown(trip.dispose);
    expect(trip.create(from: 'Вильнюс', to: 'Каунас',
      departure: DateTime(2026, 11, 20), services: const [],
      paymentMethod: 'Карта'), isTrue);
    expect(trip.assignPilot(), isTrue);
    expect(trip.acceptAssignedPilot(), isTrue);
    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      enableMapTiles: false, tripStore: trip)));
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(trip.status, DemoTripStatus.assigned,
      reason: 'An accidental tap must not advance the trip');
    await tester.drag(find.byKey(const Key('pilot-next-trip')),
      const Offset(-180, 0));
    await tester.pump();
    expect(trip.status, DemoTripStatus.assigned,
      reason: 'Swiping in the wrong direction must not advance the trip');
    for (final expected in [
      DemoTripStatus.approaching,
      DemoTripStatus.underway,
      DemoTripStatus.finished,
    ]) {
      await tester.drag(find.byKey(const Key('pilot-next-trip')),
        const Offset(180, 0));
      await tester.pump();
      expect(trip.status, expected);
    }
    expect(find.byKey(const Key('pilot-rate-passenger-panel')), findsOneWidget);
    expect(trip.ratePassengerByPilot(0), isFalse);
    expect(trip.ratePassengerByPilot(6), isFalse);
    await tester.tap(find.byKey(const Key('pilot-rate-passenger-5')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('pilot-submit-passenger-rating')));
    await tester.pump();
    expect(trip.passengerRatingByPilot, 5);
    expect(find.byKey(const Key('pilot-passenger-rating-saved')), findsOneWidget);
    expect(trip.ratePassengerByPilot(1), isFalse);
    final persisted = trip.toPersistedJson()!;
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(persisted), isTrue);
    expect(restored.passengerRatingByPilot, 5);
  });

  testWidgets('Pilot swipe cannot advance while order is paused',
      (tester) async {
    final trip = DemoTripStore();
    addTearDown(trip.dispose);
    expect(trip.create(from: 'Вильнюс', to: 'Каунас',
      departure: DateTime(2026, 11, 20), services: const [],
      paymentMethod: 'Карта'), isTrue);
    expect(trip.assignPilot(), isTrue);
    expect(trip.acceptAssignedPilot(), isTrue);
    expect(trip.advancePilot(), isTrue);
    expect(trip.togglePause(), isTrue);
    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      enableMapTiles: false, tripStore: trip)));
    await tester.drag(find.byKey(const Key('pilot-next-trip')),
      const Offset(180, 0));
    await tester.pump();
    expect(trip.status, DemoTripStatus.approaching);
    expect(trip.passengerRatingByPilot, isNull);
  });
}
