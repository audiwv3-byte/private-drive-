import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  DemoTripStore newOrder() {
    final store = DemoTripStore();
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 20, 14, 30),
      services: const ['Встреча с табличкой'],
      roundTrip: true,
      estimatedFareEur: 215,
      extrasRequireQuote: true,
    ), isTrue);
    return store;
  }

  test('An active order survives simulated app restart', () {
    final before = newOrder();
    expect(before.assignPilot(), isTrue);
    expect(before.acceptAssignedPilot(), isTrue);
    expect(before.addPilotChatMessage('Подъезжаю'), isTrue);
    final saved = before.toPersistedJson()!;
    before.dispose();

    final after = DemoTripStore();
    addTearDown(after.dispose);
    expect(after.restorePersistedJson(saved), isTrue);
    expect(after.trip!.from, 'Вильнюс');
    expect(after.trip!.to, 'Каунас');
    expect(after.trip!.roundTrip, isTrue);
    expect(after.trip!.estimatedFareEur, 215);
    expect(after.trip!.extrasRequireQuote, isTrue);
    expect(after.trip!.services, contains('Встреча с табличкой'));
    expect(after.status, DemoTripStatus.assigned);
    expect(after.pilotAccepted, isTrue);
    expect(after.pilotChatMessages, ['Подъезжаю']);
    expect(after.canPassengerCancel, isTrue);
    expect(after.cancelByPassenger(), isTrue);
    expect(after.status, DemoTripStatus.cancelled);
  });

  test('Cancelled order stays cancelled after restart', () {
    final before = newOrder();
    expect(before.cancelByPassenger(), isTrue);
    final saved = before.toPersistedJson()!;
    before.dispose();

    final after = DemoTripStore();
    addTearDown(after.dispose);
    expect(after.restorePersistedJson(saved), isTrue);
    expect(after.status, DemoTripStatus.cancelled);
    expect(after.canPassengerCancel, isFalse);
  });

  test('Invalid data never creates an order', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.restorePersistedJson('broken'), isFalse);
    expect(store.restorePersistedJson('{"version":2}'), isFalse);
    expect(store.trip, isNull);
  });

  test('Legacy saved orders without fare fields remain readable', () {
    final original = newOrder();
    final data = jsonDecode(original.toPersistedJson()!) as Map<String, dynamic>;
    original.dispose();
    data.remove('estimatedFareEur');
    data.remove('extrasRequireQuote');
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(jsonEncode(data)), isTrue);
    expect(restored.trip!.estimatedFareEur, isNull);
    expect(restored.trip!.extrasRequireQuote, isFalse);
  });

  test('Invalid fare estimate is rejected when restoring an order', () {
    final original = newOrder();
    final data = jsonDecode(original.toPersistedJson()!) as Map<String, dynamic>;
    original.dispose();
    data['estimatedFareEur'] = -5;
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(jsonEncode(data)), isFalse);
    expect(restored.trip, isNull);
  });

  test('Dispatcher chat archive survives app restart and a new order', () {
    final store = newOrder();
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.addPilotChatMessage('У входа'), isTrue);
    expect(store.addPassengerChatMessage('Выхожу'), isTrue);
    expect(store.cancelByPassenger(), isTrue);
    expect(store.create(
      from: 'Каунас', to: 'Вильнюс',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 22),
      services: const [],
    ), isTrue);
    expect(store.archivedChats, hasLength(1));
    expect(store.archivedChats.single.pilotMessages, ['У входа']);
    expect(store.archivedChats.single.passengerMessages, ['Выхожу']);
    expect(store.pilotChatMessages, isEmpty);
    final saved = store.toPersistedJson()!;
    store.dispose();

    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(saved), isTrue);
    expect(restored.archivedChats, hasLength(1));
    expect(restored.archivedChats.single.from, 'Вильнюс');
    expect(restored.archivedChats.single.passengerMessages, ['Выхожу']);
    expect(restored.trip!.from, 'Каунас');
  });

  test('Legacy chat snapshot without archives restores safely', () {
    final before = newOrder();
    final payload = jsonDecode(before.toPersistedJson()!)
        as Map<String, dynamic>;
    before.dispose();
    payload.remove('archivedChats');
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(jsonEncode(payload)), isTrue);
    expect(restored.archivedChats, isEmpty);
  });

  test('Private pilot GPS is not persisted', () {
    final store = newOrder();
    addTearDown(store.dispose);
    store.setPilotOnline(true);
    store.updatePilotLocation(54.6872, 25.2797);
    final snapshot = store.toPersistedJson()!;
    expect(snapshot, isNot(contains('pilotLatitude')));
    expect(snapshot, isNot(contains('pilotLongitude')));
    final restarted = DemoTripStore();
    addTearDown(restarted.dispose);
    expect(restarted.restorePersistedJson(snapshot), isTrue);
    expect(restarted.pilotOnline, isFalse);
    expect(restarted.pilotLatitude, isNull);
  });
}
