import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
// ignore: depend_on_referenced_packages
import 'package:geolocator_platform_interface/geolocator_platform_interface.dart';
import 'package:latlong2/latlong.dart' show LatLng;
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

class MovingLocation extends GeolocatorPlatform {
  final positions = StreamController<Position>.broadcast();
  final status = StreamController<ServiceStatus>.broadcast();

  Position fix(double latitude, double longitude) => Position(
    latitude: latitude, longitude: longitude, timestamp: DateTime.now(),
    accuracy: 5, altitude: 0, altitudeAccuracy: 0, heading: 0,
    headingAccuracy: 0, speed: 0, speedAccuracy: 0,
  );

  @override
  Future<bool> isLocationServiceEnabled() async => true;

  @override
  Future<LocationPermission> checkPermission() async =>
      LocationPermission.whileInUse;

  @override
  Future<LocationAccuracyStatus> getLocationAccuracy() async =>
      LocationAccuracyStatus.precise;

  @override
  Future<Position> getCurrentPosition({LocationSettings? locationSettings}) async =>
      fix(54.700001, 25.300002);

  @override
  Stream<Position> getPositionStream({LocationSettings? locationSettings}) =>
      positions.stream;

  @override
  Stream<ServiceStatus> getServiceStatusStream() => status.stream;
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

  testWidgets('GPS button reads device fix and uses it as pickup',
      (tester) async {
    var requests = 0;
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(
        enableMapTiles: false,
        currentPositionLoader: () async {
          requests++;
          return const LatLng(54.700001, 25.300002);
        },
      ),
    ));
    expect(requests, 0, reason: 'GPS must not start without a tap');
    await tester.tap(find.byKey(const Key('passenger-locate-me')));
    await tester.pumpAndSettle();
    expect(requests, 1);
    expect(find.byKey(const Key('passenger-locate-me')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-use-current-as-pickup')), 130,
      scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('passenger-use-current-as-pickup')),
        findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-use-current-as-pickup')));
    await tester.pump();
    expect(tester.widget<TextField>(
      find.byKey(const Key('passenger-from'))).controller!.text,
      '54.700001, 25.300002');
  });

  testWidgets('Passenger GPS follows new fixes without moving a chosen pickup',
      (tester) async {
    final platform = GeolocatorPlatform.instance;
    final moving = MovingLocation();
    GeolocatorPlatform.instance = moving;
    addTearDown(() async {
      GeolocatorPlatform.instance = platform;
      await moving.positions.close();
      await moving.status.close();
    });
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));

    expect(moving.positions.hasListener, isFalse);
    await tester.tap(find.byKey(const Key('passenger-locate-me')));
    await tester.pumpAndSettle();
    expect(moving.positions.hasListener, isTrue);

    final pickup = find.byKey(const Key('passenger-use-current-as-pickup'));
    final address = find.byKey(const Key('passenger-from'));
    moving.positions.add(moving.fix(54.710003, 25.310004));
    await tester.pump();
    await tester.scrollUntilVisible(pickup, 130,
      scrollable: find.byType(Scrollable).first);
    await tester.tap(pickup);
    await tester.pump();
    expect(tester.widget<TextField>(address).controller!.text,
      '54.710003, 25.310004');

    moving.positions.add(moving.fix(54.720005, 25.320006));
    await tester.pump();
    expect(tester.widget<TextField>(address).controller!.text,
      '54.710003, 25.310004');

    moving.status.add(ServiceStatus.disabled);
    await tester.pump();
    expect(moving.positions.hasListener, isFalse);
    expect(pickup, findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    expect(moving.status.hasListener, isFalse);
  });

  testWidgets('GPS errors are shown and do not invent passenger coordinates',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(
        enableMapTiles: false,
        currentPositionLoader: () async => throw StateError('no GPS'),
      ),
    ));
    await tester.tap(find.byKey(const Key('passenger-locate-me')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-location-error')), 130,
      scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('passenger-location-error')), findsOneWidget);
    expect(find.byKey(const Key('passenger-use-current-as-pickup')),
      findsNothing);
  });

  testWidgets('Passenger menu opens from the top left without fake features',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(enableMapTiles: false, tripStore: store),
    ));
    await tester.tap(find.byKey(const Key('passenger-open-drawer')));
    // Requested trips show a continuously rotating PD waiting indicator:
    // pumpAndSettle must not be used while that indicator is active.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byKey(const Key('passenger-navigation-drawer')), findsOneWidget);
    expect(find.byKey(const Key('passenger-drawer-history')), findsOneWidget);
    expect(find.byKey(const Key('passenger-drawer-language')), findsOneWidget);
    expect(tester.widget<ListTile>(
      find.byKey(const Key('passenger-drawer-profile'))).onTap, isNotNull);
    await tester.tap(find.byKey(const Key('passenger-drawer-history')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 450));
    expect(find.byKey(const Key('passenger-order-card')), findsOneWidget);
  });

  testWidgets('Passenger can select both route points on the map', (tester) async {
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      mapConnectivityCheck: () async => null,
    )));
    final map = find.byKey(const Key('passenger-map'));
    final selector = find.byKey(const Key('passenger-map-point-mode'));
    final form = find.byKey(const Key('passenger-form'));
    final scrollable = find.descendant(of: form, matching: find.byType(Scrollable)).first;
    final pickup = find.byKey(const Key('passenger-pick-origin-on-map'));
    final destination = find.byKey(const Key('passenger-pick-destination-on-map'));
    await tester.scrollUntilVisible(pickup, 80, scrollable: scrollable);
    tester.widget<IconButton>(pickup).onPressed!();
    await tester.pump(const Duration(milliseconds: 250));
    expect(tester.widget<SegmentedButton<bool>>(selector).selected, {false});
    tester.widget<FlutterMap>(map).options.onTap!(
      const TapPosition(Offset.zero, Offset.zero), const LatLng(54.70, 25.30));
    await tester.pump();
    await tester.scrollUntilVisible(destination, 80, scrollable: scrollable);
    tester.widget<IconButton>(destination).onPressed!();
    await tester.pump(const Duration(milliseconds: 250));
    expect(tester.widget<SegmentedButton<bool>>(selector).selected, {true});
    tester.widget<FlutterMap>(map).options.onTap!(
      const TapPosition(Offset.zero, Offset.zero), const LatLng(54.69, 25.27));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 260));
    final sheet = tester.widget<DraggableScrollableSheet>(
      find.byKey(const Key('passenger-trip-bottom-sheet')));
    sheet.controller!.jumpTo(0.94);
    tester.state<ScrollableState>(scrollable).position.jumpTo(0);
    await tester.pump();
    for (final (key, expected) in [
      ('passenger-from', '54.700000, 25.300000'),
      ('passenger-to', '54.690000, 25.270000'),
    ]) {
      final field = find.byKey(Key(key));
      await tester.scrollUntilVisible(field, 100, scrollable: scrollable);
      expect(tester.widget<TextField>(field).controller!.text, expected);
    }
    await tester.pumpWidget(const SizedBox.shrink());
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

  testWidgets('Android passenger map allows only primary or backup keyless OSM tiles in both themes',
      (tester) async {
    // An unreachable tile endpoint can trigger the app's automatic switch
    // before the first expectation. Both explicitly approved templates must
    // remain keyless OSM PNG URLs: never accept CARTO or arbitrary hosts.
    const approvedOsmTemplates = <String>{
      'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      'https://tile.openstreetmap.de/{z}/{x}/{y}.png',
    };
    void expectApprovedOsmTileLayer(TileLayer layer) {
      expect(approvedOsmTemplates, contains(layer.urlTemplate));
      expect(layer.fallbackUrl, isNull);
      expect(layer.tileProvider, isA<DemoDirectNetworkTileProvider>());
      expect(layer.tileProvider.headers['User-Agent'],
          'PRIVATE DRIVE demo Android visual QA');
    }

    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: true),
    ));
    final tileFinder = find.byKey(const Key('passenger-map-tiles'));
    expect(tileFinder, findsOneWidget);
    expectApprovedOsmTileLayer(tester.widget<TileLayer>(tileFinder));
    expect(find.ancestor(of: tileFinder, matching: find.byType(ColorFiltered)),
        findsOneWidget);
    tester.widget<IconButton>(find.byKey(
        const Key('passenger-map-day-night'))).onPressed!();
    await tester.pump();
    expectApprovedOsmTileLayer(tester.widget<TileLayer>(tileFinder));
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

  testWidgets('Passenger map follows pilot and allows manual camera mode',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    final map = MapController();
    addTearDown(map.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: true,
      tripStore: store,
      passengerMapController: map,
      mapConnectivityCheck: () async => null,
    )));
    await tester.pump();
    store.setPilotOnline(true);
    store.updatePilotLocation(54.6872, 25.2797);
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('passenger-follow-pilot')), findsOneWidget);
    expect((map.camera.center.latitude - 54.6872).abs(), lessThan(0.001));
    expect((map.camera.center.longitude - 25.2797).abs(), lessThan(0.001));

    await tester.tap(find.byKey(const Key('passenger-follow-pilot')));
    await tester.pump();
    store.updatePilotLocation(54.7000, 25.3000);
    await tester.pump();
    await tester.pump();
    expect((map.camera.center.latitude - 54.6872).abs(), lessThan(0.001),
        reason: 'Manual mode must not recenter the map');

    await tester.tap(find.byKey(const Key('passenger-follow-pilot')));
    await tester.pump();
    await tester.pump();
    expect((map.camera.center.latitude - 54.7000).abs(), lessThan(0.001));
  });

  testWidgets('Passenger uses lime pin instead of car for live pilot',
      (tester) async {
    final store = makeOrder();
    addTearDown(store.dispose);
    store.setPilotOnline(true);
    store.updatePilotLocation(54.6872, 25.2797);
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: true, tripStore: store,
      mapConnectivityCheck: () async => null,
    )));
    await tester.pump();
    final icon = tester.widget<Icon>(
      find.byKey(const Key('passenger-pilot-map-marker')));
    expect(icon.icon, Icons.location_on);
    expect(icon.color, const Color(0xFFB6FF36));
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
