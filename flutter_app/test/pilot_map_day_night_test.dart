import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:private_drive/demo_map_tile_provider.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  testWidgets('Day/night switch is compact and does not reset pilot trip',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    store.setPilotOnline(true);
    store.updatePilotLocation(54.6872, 25.2797);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      departure: DateTime(2026, 11, 18),
      paymentMethod: 'Карта', services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      enableMapTiles: true, loadMapTiles: false, tripStore: store,
    )));
    await tester.pump();
    expect(find.byKey(const Key('pilot-map-day-night')), findsOneWidget);
    expect(find.text('ДЕНЬ'), findsOneWidget);
    expect(find.byKey(const Key('pilot-location-marker')), findsOneWidget);
    final icon = tester.widget<Icon>(
      find.byKey(const Key('pilot-location-marker')));
    expect(icon.icon, Icons.directions_car_filled);
    expect(icon.color, const Color(0xFF172B3F));
    expect(find.byKey(const Key('pilot-pickup-preview-pin')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-map-day-night')));
    await tester.pump();
    final toggle = tester.widget<IconButton>(
      find.byKey(const Key('pilot-map-day-night')));
    expect(toggle.tooltip, 'Дневная карта');
    expect(find.text('НОЧЬ'), findsOneWidget);
    expect(store.status, DemoTripStatus.approaching);
    expect(find.byKey(const Key('pilot-location-marker')), findsOneWidget);
    expect(find.byKey(const Key('pilot-pickup-preview-pin')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-map-day-night')));
    await tester.pump();
    expect(tester.widget<IconButton>(
      find.byKey(const Key('pilot-map-day-night'))).tooltip, 'Ночная карта');
    expect(store.status, DemoTripStatus.approaching);
  });
  testWidgets('Pilot live tile layer uses real sources with day/night themes',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PilotDemo(enableMapTiles: true, loadMapTiles: true),
    ));
    final tile = find.byKey(const Key('pilot-map-tiles'));
    expect(tile, findsOneWidget);
    expect(tester.widget<TileLayer>(tile).urlTemplate,
        contains('tile.openstreetmap.org'));
    final provider = tester.widget<TileLayer>(tile).tileProvider;
    expect(provider, isA<DemoDirectNetworkTileProvider>());
    expect(provider.headers['User-Agent'],
        'PRIVATE DRIVE demo Android visual QA');
    expect(find.ancestor(of: tile, matching: find.byType(ColorFiltered)),
        findsNothing);
    expect(find.byKey(const Key('pilot-map-theme-status')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-map-day-night')));
    await tester.pump();
    expect(find.text('НОЧЬ'), findsOneWidget);
    expect(tester.widget<TileLayer>(tile).urlTemplate,
        contains('cartocdn.com/dark_all'));
  });

}
