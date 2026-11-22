import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  test('Pickup wait: three minutes free, then 25 cents per started minute', () {
    final trip = DemoTripStore();
    expect(trip.create(
      from: 'Vilnius', to: 'Trakai', paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 23), services: const [],
    ), isTrue);
    expect(trip.assignPilot(), isTrue);
    expect(trip.acceptAssignedPilot(), isTrue);
    expect(trip.advancePilot(), isTrue);
    final arrived = DateTime(2026, 11, 22, 10);
    expect(trip.markArrived(now: arrived), isTrue);
    expect(trip.pickupWaitingChargeCents(now: arrived.add(const Duration(minutes: 3))), 0);
    expect(trip.pickupWaitingChargeCents(now: arrived.add(const Duration(minutes: 3, seconds: 1))), 25);
    expect(trip.pickupWaitingChargeCents(now: arrived.add(const Duration(minutes: 4, seconds: 1))), 50);
    trip.dispose();
  });

  test('Stops are cumulative; trip cannot advance while paused', () {
    final trip = DemoTripStore();
    expect(trip.create(
      from: 'Vilnius', to: 'Trakai', paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 23), services: const [],
    ), isTrue);
    expect(trip.assignPilot(), isTrue);
    expect(trip.acceptAssignedPilot(), isTrue);
    expect(trip.advancePilot(), isTrue);
    expect(trip.markArrived(), isTrue);
    expect(trip.advancePilot(), isTrue);
    final stopped = DateTime(2026, 11, 22, 10);
    expect(trip.togglePause(now: stopped), isTrue);
    expect(trip.advancePilot(), isFalse);
    expect(trip.togglePause(now: stopped.add(const Duration(minutes: 2))), isTrue);
    expect(trip.totalStopWaiting(), const Duration(minutes: 2));
    expect(trip.advancePilot(), isTrue);
    expect(trip.status, DemoTripStatus.finished);
    trip.dispose();
  });
}
