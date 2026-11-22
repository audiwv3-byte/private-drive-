import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  testWidgets('Queued offer never replaces or clears active trip route',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас', paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18), services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue); // pickup
    expect(store.advancePilot(), isTrue); // underway
    expect(store.status, DemoTripStatus.underway);
    const routeFixture = [
      LatLng(54.6872, 25.2797), LatLng(54.8985, 23.9036),
    ];
    var alertCount = 0;
    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      tripStore: store,
      enableMapTiles: true,
      loadMapTiles: false,
      testRoadPoints: routeFixture,
      onIncomingSound: () => alertCount++,
    )));
    expect(find.byKey(const Key('pilot-road-route')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('pilot-simulate-offer')));
    await tester.tap(find.byKey(const Key('pilot-simulate-offer')));
    await tester.pump();
    expect(alertCount, 1);
    expect(find.byKey(const Key('pilot-next-offer')), findsOneWidget);
    expect(store.status, DemoTripStatus.underway);
    expect(store.trip?.to, 'Каунас');
    expect(find.byKey(const Key('pilot-road-route')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('pilot-accept-next')));
    await tester.tap(find.byKey(const Key('pilot-accept-next')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-next-queued-status')), findsOneWidget);
    expect(store.status, DemoTripStatus.underway);
    expect(store.trip?.to, 'Каунас');
    expect(find.byKey(const Key('pilot-road-route')), findsOneWidget);
    // Only ending the current trip removes its navigation.
    await tester.ensureVisible(find.byKey(const Key('pilot-final-destination-mode')));
    await tester.tap(find.byKey(const Key('pilot-final-destination-mode')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('pilot-next-trip')));
    await tester.drag(find.byKey(const Key('pilot-next-trip-handle')),
      Offset((tester.getSize(find.byKey(const Key('pilot-next-trip'))).width - 52), 0));
    await tester.pump();
    expect(store.status, DemoTripStatus.finished);
    expect(find.byKey(const Key('pilot-road-route')), findsNothing);
  });

  testWidgets('City route stays visible on active underway phase',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Тракай', paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18), services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      tripStore: store, enableMapTiles: true, loadMapTiles: false,
      testRoadPoints: const [LatLng(54.6872, 25.2797),
        LatLng(54.6389, 24.9342)],
    )));
    expect(find.byKey(const Key('pilot-road-route')), findsOneWidget);
    expect(find.text('Назначение: Тракай'), findsOneWidget);
  });
}
