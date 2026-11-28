import 'package:flutter/foundation.dart' show TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
// The platform fake exercises the real passenger GPS loader without hardware.
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

Position passengerFix({
  double accuracy = 12,
  bool hasAccuracy = true,
  Duration age = Duration.zero,
  double latitude = 54.700001,
}) => Position(
  latitude: latitude,
  longitude: 25.300002,
  timestamp: DateTime.now().subtract(age),
  accuracy: accuracy,
  hasAccuracy: hasAccuracy,
  altitude: 0,
  altitudeAccuracy: 0,
  heading: 0,
  headingAccuracy: 0,
  speed: 0,
  speedAccuracy: 0,
);

class PassengerLocationPlatform extends GeolocatorPlatform {
  LocationSettings? requestedSettings;

  @override
  Future<bool> isLocationServiceEnabled() async => true;

  @override
  Future<LocationPermission> checkPermission() async =>
      LocationPermission.whileInUse;

  @override
  Future<Position> getCurrentPosition({LocationSettings? locationSettings}) async {
    requestedSettings = locationSettings;
    return passengerFix();
  }

  @override
  Stream<ServiceStatus> getServiceStatusStream() =>
      const Stream<ServiceStatus>.empty();
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
          return passengerFix();
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
    final from = find.byKey(const Key('passenger-from'));
    await tester.scrollUntilVisible(from, 100, scrollable: find.byType(Scrollable).first);
    expect(tester.widget<TextField>(from).controller!.text,
      '54.700001, 25.300002');
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

  testWidgets('Native passenger fix centers the map and shows its accuracy',
      (tester) async {
    final savedPlatform = GeolocatorPlatform.instance;
    final platform = PassengerLocationPlatform();
    GeolocatorPlatform.instance = platform;
    addTearDown(() => GeolocatorPlatform.instance = savedPlatform);
    final map = MapController();
    addTearDown(map.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      passengerMapController: map,
      mapConnectivityCheck: () async => null,
    )));
    expect(platform.requestedSettings, isNull);

    await tester.tap(find.byKey(const Key('passenger-locate-me')));
    await tester.pump();
    await tester.pump();

    const point = LatLng(54.700001, 25.300002);
    expect(platform.requestedSettings?.accuracy, LocationAccuracy.high);
    expect(map.camera.center.latitude, closeTo(point.latitude, 0.000001));
    expect(map.camera.center.longitude, closeTo(point.longitude, 0.000001));
    final layer = tester.widget<MarkerLayer>(find.byType(MarkerLayer));
    expect(layer.markers.single.point, point);
    expect(find.byKey(const Key('passenger-picked-pickup-marker')), findsNothing);
    expect(find.byKey(const Key('passenger-gps-marker')), findsOneWidget);
    final circle = tester.widget<CircleLayer>(find.byType(CircleLayer)).circles.single;
    expect(circle.point, point);
    expect(circle.useRadiusInMeter, isTrue);
    expect(circle.radius, 12);
  }, variant: const TargetPlatformVariant({
    TargetPlatform.android, TargetPlatform.iOS,
  }));

  final invalidFixes = <String, Position Function()>{
    'weak': () => passengerFix(accuracy: 350),
    'missing accuracy': () => passengerFix(hasAccuracy: false),
    'zero accuracy': () => passengerFix(accuracy: 0),
    'non-finite accuracy': () => passengerFix(accuracy: double.nan),
    'stale': () => passengerFix(age: const Duration(minutes: 1)),
    'future': () => passengerFix(age: const Duration(seconds: -5)),
    'invalid coordinates': () => passengerFix(latitude: 91),
  };
  for (final entry in invalidFixes.entries) {
    testWidgets('Passenger rejects a ${entry.key} GPS fix and keeps manual pickup',
        (tester) async {
      await tester.pumpWidget(MaterialApp(home: PassengerDemo(
        enableMapTiles: false,
        currentPositionLoader: () async => entry.value(),
      )));

      await tester.tap(find.byKey(const Key('passenger-locate-me')));
      await tester.pumpAndSettle();
      final error = find.byKey(const Key('passenger-location-error'));
      await tester.scrollUntilVisible(error, 130,
        scrollable: find.byType(Scrollable).first);
      expect(error, findsOneWidget);
      expect(find.byKey(const Key('passenger-use-current-as-pickup')), findsNothing);

      if (entry.key != 'weak') return;
      final from = find.byKey(const Key('passenger-from'));
      await tester.scrollUntilVisible(from, 130,
        scrollable: find.byType(Scrollable).first);
      final field = tester.widget<TextField>(from).controller!;
      expect(field.text, isEmpty);
      await tester.enterText(from, 'Gedimino pr. 9, Vilnius');
      await tester.pump();
      final confirm = find.byKey(const Key('passenger-confirm-pickup-address'));
      await tester.ensureVisible(confirm);
      await tester.tap(confirm);
      await tester.pump();
      expect(field.text, 'Gedimino pr. 9, Vilnius');
      expect(confirm, findsNothing);
    });
  }

  testWidgets('Expired GPS cannot replace a confirmed pickup', (tester) async {
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false,
      currentPositionLoader: () async => passengerFix(
        age: const Duration(seconds: 25),
      ),
    )));
    await tester.tap(find.byKey(const Key('passenger-locate-me')));
    await tester.pumpAndSettle();
    final confirm = find.byKey(const Key('passenger-use-current-as-pickup'));
    await tester.scrollUntilVisible(confirm, 130,
      scrollable: find.byType(Scrollable).first);
    await tester.tap(confirm);
    await tester.pump();
    final from = find.byKey(const Key('passenger-from'));
    await tester.scrollUntilVisible(from, 100, scrollable: find.byType(Scrollable).first);
    final field = tester.widget<TextField>(from).controller!;
    expect(field.text, '54.700001, 25.300002');

    await tester.pump(const Duration(seconds: 6));
    expect(confirm, findsNothing);
    expect(field.text, '54.700001, 25.300002');
  });

  testWidgets('A map tap previews the exact point until pickup is confirmed',
      (tester) async {
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      mapConnectivityCheck: () async => null,
    )));
    final map = find.byKey(const Key('passenger-map'));
    final layers = find.byType(MarkerLayer);
    final picked = find.byKey(const Key('passenger-picked-pickup-marker'));
    final at = tester.getTopLeft(map) + const Offset(360, 180);

    await tester.tapAt(at);
    await tester.pump(const Duration(milliseconds: 300));
    final preview = tester.widget<MarkerLayer>(layers).markers.single.point;
    expect(picked, findsNothing);
    expect(find.byKey(const Key('passenger-preview-pickup-marker')), findsOneWidget);

    await tester.tap(find.byKey(const Key('passenger-cancel-map-pickup')));
    await tester.pump();
    expect(tester.widget<MarkerLayer>(layers).markers, isEmpty);

    await tester.tapAt(at);
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byKey(const Key('passenger-confirm-map-pickup')));
    await tester.pump();
    expect(picked, findsOneWidget);
    expect(tester.widget<MarkerLayer>(layers).markers.single.point, preview);
    final from = find.byKey(const Key('passenger-from'));
    await tester.scrollUntilVisible(from, 100, scrollable: find.byType(Scrollable).first);
    expect(tester.widget<TextField>(from).controller!.text,
      '${preview.latitude.toStringAsFixed(6)}, ${preview.longitude.toStringAsFixed(6)}');
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
      find.byKey(const Key('passenger-drawer-profile'))).enabled, isFalse);
    await tester.tap(find.byKey(const Key('passenger-drawer-history')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 450));
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
