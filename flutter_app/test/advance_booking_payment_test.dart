import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  final date = DateTime(2026, 12, 1, 12);

  test('Advance booking rejects cash but allows other payment methods', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас', departure: date,
      paymentMethod: 'Наличные', advanceBooking: true, services: const []), isFalse);
    expect(store.trip, isNull);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас', departure: date,
      paymentMethod: 'Карта', advanceBooking: true, services: const []), isTrue);
    expect(store.trip!.advanceBooking, isTrue);
    expect(store.trip!.paymentMethod, 'Карта');

    final saved = store.toPersistedJson()!;
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(saved), isTrue);
    expect(restored.trip!.advanceBooking, isTrue);
  });

  test('Immediate cash ride remains allowed for cash-enabled pilot', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(from: 'А', to: 'Б', departure: DateTime.now(),
      paymentMethod: 'Наличные', services: const []), isTrue);
    expect(store.trip!.advanceBooking, isFalse);
    expect(store.assignPilot(), isFalse);
    store.setPilotAcceptsCash(true);
    expect(store.assignPilot(), isTrue);
  });

  test('After booking, services and payment are immutable', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    final original = <String>['Встреча с табличкой'];
    expect(store.create(from: 'Вильнюс', to: 'Каунас',
      departure: date, paymentMethod: 'Карта',
      advanceBooking: true, services: original), isTrue);
    original.add('Кофе');
    expect(store.trip!.services, ['Встреча с табличкой']);
    expect(() => store.trip!.services.add('Кофе'), throwsUnsupportedError);
    expect(store.create(from: 'Вильнюс', to: 'Тракай',
      departure: date, paymentMethod: 'PayPal',
      advanceBooking: true, services: const ['Кофе']), isFalse);
    expect(store.trip!.paymentMethod, 'Карта');
    expect(store.trip!.services, ['Встреча с табличкой']);
    expect(store.trip!.advanceBooking, isTrue);
  });

  test('Route modifications do not change original payment automatically', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(from: 'Вильнюс', to: 'Каунас', departure: date,
      paymentMethod: 'Карта', advanceBooking: true,
      services: const ['Дополнительная остановка по согласованию']), isTrue);
    expect(store.trip!.paymentMethod, 'Карта');
    expect(store.trip!.advanceBooking, isTrue);
  });
}
