import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_orders_demo.dart';

DemoTripStore prepared() {
  final store = DemoTripStore();
  assert(store.create(
    from: 'Вильнюс', to: 'Каунас',
    departure: DateTime(2026, 11, 20),
    services: const [], paymentMethod: 'Карта'));
  assert(store.assignPilot());
  assert(store.acceptAssignedPilot());
  assert(store.advancePilot());
  return store;
}

void main() {
  test('Pickup waiting is free for 3 min, then 0.30 per started minute', () {
    final store = prepared();
    addTearDown(store.dispose);
    final start = DateTime(2026, 11, 20, 15);
    expect(store.pickupWaitingChargeCents(now: start.add(const Duration(hours: 1))), 0);
    expect(store.markArrived(now: start), isTrue);
    expect(store.markArrived(now: start), isFalse);
    expect(store.pickupWaitingChargeCents(
      now: start.add(const Duration(minutes: 2, seconds: 59))), 0);
    expect(store.pickupWaitingChargeCents(
      now: start.add(const Duration(minutes: 3))), 0);
    expect(store.pickupWaitingChargeCents(
      now: start.add(const Duration(minutes: 3, seconds: 1))), 30);
    expect(store.pickupWaitingChargeCents(
      now: start.add(const Duration(minutes: 4))), 30);
    expect(store.pickupWaitingChargeCents(
      now: start.add(const Duration(minutes: 4, seconds: 1))), 60);
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(store.toPersistedJson()!), isTrue);
    expect(restored.pickupWaitingChargeCents(
      now: start.add(const Duration(minutes: 4, seconds: 1))), 60);
    expect(store.advancePilot(), isTrue);
    final frozen = store.pickupWaitingChargeCents();
    expect(store.pickupWaitingChargeCents(now: start.add(
      const Duration(days: 7))), frozen);
  });

  testWidgets('Pilot arrival starts timer and passenger sees waiting', (tester) async {
    final store = prepared();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home:
      PilotDemo(enableMapTiles: false, tripStore: store)));
    expect(find.byKey(const Key('pilot-arrived-at-pickup')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-arrived-at-pickup')));
    await tester.pump();
    expect(store.isWaitingAtPickup, isTrue);
    expect(find.byKey(const Key('pilot-pickup-waiting-meter')), findsOneWidget);
    await tester.pumpWidget(MaterialApp(home:
      PassengerOrdersDemo(tripStore: store)));
    await tester.pump();
    expect(find.byKey(const Key('passenger-pickup-waiting-fee')), findsOneWidget);
    expect(find.textContaining('бесплатное ожидание'), findsOneWidget);
  });
}
