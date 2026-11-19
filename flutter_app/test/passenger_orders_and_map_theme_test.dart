import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:private_drive/demo_map_tile_provider.dart';
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

  testWidgets('Passenger menu opens from the top left without fake features',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(enableMapTiles: false, tripStore: store),
    ));
    await tester.tap(find.byKey(const Key('passenger-open-drawer')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-navigation-drawer')), findsOneWidget);
    expect(find.byKey(const Key('passenger-drawer-history')), findsOneWidget);
    expect(find.byKey(const Key('passenger-drawer-language')), findsOneWidget);
    expect(tester.widget<ListTile>(
      find.byKey(const Key('passenger-drawer-profile'))).enabled, isFalse);
    await tester.tap(find.byKey(const Key('passenger-drawer-history')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-order-card')), findsOneWidget);
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

  testWidgets('Android passenger map uses keyless OSM tiles in both themes',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: true),
    ));
    final tileFinder = find.byKey(const Key('passenger-map-tiles'));
    expect(tileFinder, findsOneWidget);
    final day = tester.widget<TileLayer>(tileFinder);
    expect(day.urlTemplate, contains('tile.openstreetmap.org'));
    expect(day.fallbackUrl, isNull);
    expect(day.tileProvider, isA<DemoDirectNetworkTileProvider>());
    expect(day.tileProvider.headers['User-Agent'],
        'PRIVATE DRIVE demo Android visual QA');
    expect(find.ancestor(of: tileFinder, matching: find.byType(ColorFiltered)),
        findsOneWidget);
    tester.widget<IconButton>(find.byKey(
        const Key('passenger-map-day-night'))).onPressed!();
    await tester.pump();
    final night = tester.widget<TileLayer>(tileFinder);
    expect(night.urlTemplate, contains('tile.openstreetmap.org'));
    expect(find.text('ДЕНЬ'), findsNothing);
    expect(find.text('НОЧЬ'), findsNothing);
    expect(find.ancestor(of: tileFinder, matching: find.byType(ColorFiltered)),
        findsOneWidget);
  });

  testWidgets('Map network error is visible and retry re-checks the server',
      (tester) async {
    var checks = 0;
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(
        enableMapTiles: true,
        mapConnectivityCheck: () async {
          checks++;
          return checks == 1 ? 'Тестовая ошибка HTTPS' : null;
        },
      ),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('passenger-map-load-error')), findsOneWidget);
    expect(find.text('Тестовая ошибка HTTPS'), findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-map-retry')));
    await tester.pump();
    await tester.pump();
    expect(checks, 2);
    expect(find.text('Тестовая ошибка HTTPS'), findsNothing);
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
  });

  testWidgets('Passenger sees only real fresh pilot GPS for an active order',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false, tripStore: store,
    )));
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-pilot-location-status')),
      160,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(find.text('Местоположение пилота пока недоступно'),
        findsOneWidget);
    store.setPilotOnline(true);
    store.updatePilotLocation(54.6872, 25.2797);
    await tester.pump();
    expect(find.text('Местоположение пилота · GPS обновляется'),
        findsOneWidget);
    store.setPilotOnline(false);
    await tester.pump();
    expect(find.text('Местоположение пилота пока недоступно'),
        findsOneWidget);
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
