import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_orders_demo.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/passenger_demo.dart';

DemoTripStore makeOrder() {
  final store = DemoTripStore();
  expect(store.create(
    from: 'Вильнюс', to: 'Каунас', paymentMethod: 'PayPal',
    departure: DateTime(2026, 11, 18), services: const [],
  ), isTrue);
  return store;
}

void main() {
  test('Passenger cancellation cannot interrupt an underway trip', () {
    final store = makeOrder();
    addTearDown(store.dispose);
    expect(store.canPassengerCancel, isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.cancelByPassenger(), isFalse);
    expect(store.status, DemoTripStatus.approaching);
    expect(store.advancePilot(), isTrue);
    expect(store.cancelByPassenger(), isFalse);
    expect(store.status, DemoTripStatus.underway);
    expect(store.advancePilot(), isTrue);
    expect(store.rateFinishedTrip(tripStars: 5, serviceStars: 4), isTrue);
  });

  testWidgets('Passenger order survives screen navigation and can be cancelled',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    Widget page() => MaterialApp(home: PassengerOrdersDemo(tripStore: store));
    await tester.pumpWidget(page());
    expect(find.byKey(const Key('passenger-order-card')), findsOneWidget);
    expect(find.textContaining('Вильнюс → Каунас'), findsOneWidget);
    await tester.pumpWidget(const MaterialApp(home: Scaffold(
      body: Text('Главная страница'))));
    await tester.pumpWidget(page());
    expect(find.byKey(const Key('passenger-order-card')), findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-cancel-order')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('passenger-confirm-cancel')));
    await tester.pumpAndSettle();
    expect(store.status, DemoTripStatus.cancelled);
    expect(find.byKey(const Key('passenger-cancel-order')), findsNothing);
    expect(store.create(from:'Каунас', to:'Вильнюс',
      paymentMethod:'Карта', departure:DateTime(2026,11,19),
      services:const []), isTrue);
  });

  testWidgets('Pilot messages appear in passenger order and passenger can reply',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.addPilotChatMessage('Я подъезжаю'), isTrue);
    await tester.pumpWidget(MaterialApp(
      home: PassengerOrdersDemo(tripStore: store)));
    expect(find.text('Я подъезжаю'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('passenger-chat-input')));
    await tester.enterText(find.byKey(const Key('passenger-chat-input')),
      'Вижу автомобиль');
    await tester.tap(find.byKey(const Key('passenger-chat-send')));
    await tester.pump();
    expect(store.passengerChatMessages, ['Вижу автомобиль']);
  });

  testWidgets('Passenger can switch map day and night in offline preview',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
    expect(find.byKey(const Key('passenger-map-day-night')), findsOneWidget);
    expect(find.byTooltip('Ночная карта'), findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-map-day-night')));
    await tester.pump();
    expect(find.byTooltip('Дневная карта'), findsOneWidget);
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
  });

  testWidgets('Pilot can switch day and night without leaving map',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: PilotDemo(
      enableMapTiles: true, loadMapTiles: false)));
    expect(find.byKey(const Key('pilot-map-day-night')), findsOneWidget);
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.byTooltip('Ночная карта'), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-map-day-night')));
    await tester.pump();
    expect(find.byTooltip('Дневная карта'), findsOneWidget);
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
  });
}
