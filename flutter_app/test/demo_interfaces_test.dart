import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/main.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({
    'pd_native_permissions_onboarding_v1': true,
  }));
  test('Waze uses native app scheme rather than an embedded web URL', () {
    expect(privateDriveWazeAppUri.scheme, 'waze');
    expect(privateDriveWazeAppUri.scheme, isNot('https'));
    expect(privateDriveWazeAppUri.host, isEmpty);
  });

  testWidgets('Offline entry requires taxi or transfer choice before booking',
      (tester) async {
    expect(apiBaseUrl, isEmpty);
    final view = tester.view;
    view.physicalSize = const Size(390, 560);
    view.devicePixelRatio = 1;
    addTearDown(view.resetPhysicalSize);
    addTearDown(view.resetDevicePixelRatio);
    await tester.pumpWidget(const PrivateDriveApp(enableOfflinePreview: true));
    await tester.pumpAndSettle();
    final demoEntry = find.byKey(const Key('open-offline-demo'));
    expect(demoEntry.hitTestable(), findsOneWidget);
    await tester.tap(demoEntry);
    await tester.pumpAndSettle();

    // The offline-only hub exposes all three DEMO roles. This does not
    // change the separate passenger-only and server-authorized admin shells.
    expect(find.byKey(const Key('open-passenger-preview')), findsOneWidget);
    expect(find.byKey(const Key('open-pilot-preview')), findsOneWidget);
    expect(find.byKey(const Key('open-dispatcher-preview')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-title')), findsNothing);
    view.resetPhysicalSize();
    view.resetDevicePixelRatio();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-passenger-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-entry-title')), findsOneWidget);
    expect(find.byKey(const Key('passenger-form')), findsNothing);
    await tester.ensureVisible(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(find.byType(PassengerDemo), findsOneWidget);
    expect(find.text('Трансфер · выбранный тип поездки'), findsOneWidget);
    expect(find.byKey(const Key('passenger-ride-type')), findsNothing);
    expect(find.byKey(const Key('passenger-form')), findsOneWidget);
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
    expect(find.byType(PilotDemo), findsNothing);
  });

  testWidgets('Offline role hub opens pilot and dispatcher without passenger UI',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PrivateDriveDemo(enableMapTiles: false),
    ));
    await tester.pumpAndSettle();
    final pilot = find.byKey(const Key('open-pilot-preview'));
    final dispatcher = find.byKey(const Key('open-dispatcher-preview'));
    expect(find.byKey(const Key('open-passenger-preview')), findsOneWidget);
    expect(pilot, findsOneWidget);
    expect(dispatcher, findsOneWidget);

    await tester.ensureVisible(pilot);
    await tester.tap(pilot);
    await tester.pumpAndSettle();
    // The pilot starts offline in the dedicated POWER cabin. The map is
    // deliberately opened only after the pilot opts into the local shift.
    expect(find.byKey(const Key('pilot-power-toggle')), findsOneWidget);
    expect(find.byKey(const Key('passenger-form')), findsNothing);
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsNothing);
    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);

    // The pilot map has no AppBar back button by design. Pop its route
    // directly rather than using pageBack(), which requires a visible back
    // control and would incorrectly constrain the fullscreen pilot UX.
    Navigator.of(tester.element(find.byKey(const Key('pilot-map-surface'))))
        .pop(); // Map -> pilot POWER cabin.
    await tester.pumpAndSettle();
    Navigator.of(tester.element(find.byKey(const Key('pilot-power-toggle'))))
        .pop(); // Pilot POWER cabin -> three-role hub.
    await tester.pumpAndSettle();
    await tester.ensureVisible(dispatcher);
    await tester.tap(dispatcher);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('dispatcher-open-drawer')), findsOneWidget);
    expect(find.byKey(const Key('pilot-map-surface')), findsNothing);
    expect(find.byKey(const Key('passenger-form')), findsNothing);
  });

  testWidgets('Pilot gets only full-screen map surface and local trip controls',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: PilotDemo(enableMapTiles: false)));
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.text('GPS выключен'), findsOneWidget);
    expect(find.byKey(const Key('pilot-open-waze')), findsOneWidget);
    expect(find.text('Waze'), findsOneWidget);
    expect(find.text('Нет активной поездки'), findsOneWidget);
    expect(find.text('К пассажиру'), findsOneWidget);
    expect(find.text('Откуда'), findsNothing);
    expect(find.text('Куда'), findsNothing);
    expect(find.textContaining('Заказать поездку'), findsNothing);
    expect(find.byType(Drawer), findsNothing);
    expect(find.byType(BottomNavigationBar), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.text('Администратор'), findsNothing);
    expect(find.text('Диспетчер'), findsNothing);

    await tester.drag(find.byKey(const Key('pilot-next-trip-handle')),
      Offset((tester.getSize(find.byKey(const Key('pilot-next-trip'))).width - 52), 0));
    await tester.pump();
    expect(find.text('Едем к пассажиру'), findsOneWidget);
    expect(find.text('В путь'), findsOneWidget);

    // No tripStore: standalone cockpit only cycles mock display stages.
    // Actual arrival, stop and resume are covered by store-backed tests.
    await tester.drag(find.byKey(const Key('pilot-next-trip-handle')),
      Offset(tester.getSize(find.byKey(const Key('pilot-next-trip'))).width - 52, 0));
    await tester.pump();
    expect(find.text('Завершить'), findsOneWidget);
    await tester.drag(find.byKey(const Key('pilot-next-trip-handle')),
      Offset(tester.getSize(find.byKey(const Key('pilot-next-trip'))).width - 52, 0));
    await tester.pump();
    expect(find.text('Нет активной поездки'), findsOneWidget);
  });
  testWidgets('Pilot GPS stream updates map state locally and can be disabled',
      (tester) async {
    final controller = StreamController<LatLng>.broadcast(sync: true);
    addTearDown(controller.close);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, positions: controller.stream),
    ));
    expect(find.byKey(const Key('pilot-enable-gps')), findsOneWidget);
    expect(find.byKey(const Key('pilot-disable-gps')), findsNothing);

    await tester.tap(find.byKey(const Key('pilot-enable-gps')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-enable-gps')), findsNothing);
    expect(find.byKey(const Key('pilot-disable-gps')), findsOneWidget);

    controller.add(const LatLng(54.6872, 25.2797));
    await tester.pump();
    expect(find.text('GPS активен · только на устройстве'), findsOneWidget);
    expect(find.byKey(const Key('pilot-center-map')), findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-disable-gps')));
    await tester.pump();
    expect(find.text('GPS выключен'), findsOneWidget);
    expect(find.byKey(const Key('pilot-enable-gps')), findsOneWidget);
    expect(find.byKey(const Key('pilot-disable-gps')), findsNothing);
    expect(find.byKey(const Key('pilot-center-map')), findsNothing);
    expect(find.text('Администратор'), findsNothing);
    expect(find.text('Диспетчер'), findsNothing);
  });

  testWidgets('Pilot camera follows successive GPS fixes, including after pan',
      (tester) async {
    final positions = StreamController<LatLng>.broadcast(sync: true);
    final map = MapController();
    addTearDown(positions.close);
    addTearDown(map.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(
        positions: positions.stream,
        mapController: map,
        loadMapTiles: false,
      ),
    ));
    await tester.tap(find.byKey(const Key('pilot-enable-gps')));
    await tester.pump();

    const first = LatLng(54.6872, 25.2797);
    const second = LatLng(54.7002, 25.3007);
    const third = LatLng(54.7202, 25.3207);
    positions.add(first);
    await tester.pump();
    expect(map.camera.center.latitude, closeTo(first.latitude, 0.0001));
    expect(map.camera.center.longitude, closeTo(first.longitude, 0.0001));
    final marker = tester.widget<Icon>(
        find.byKey(const Key('pilot-location-marker')));
    expect(marker.icon, Icons.local_taxi_rounded);
    expect(marker.color, const Color(0xFFDDC184));

    // Panning should not silently disable GPS follow on later fixes.
    await tester.drag(find.byKey(const Key('pilot-map-surface')),
        const Offset(70, 25));
    await tester.pumpAndSettle();
    positions.add(second);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 650));
    expect(map.camera.center.latitude, closeTo(second.latitude, 0.0001));
    expect(map.camera.center.longitude, closeTo(second.longitude, 0.0001));

    // Explicit recenter is not a one-time-only follow setting.
    await tester.tap(find.byKey(const Key('pilot-center-map')));
    await tester.pump();
    positions.add(third);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 650));
    expect(map.camera.center.latitude, closeTo(third.latitude, 0.0001));
    expect(map.camera.center.longitude, closeTo(third.longitude, 0.0001));

    // A southbound pilot arrow points south, rather than always north.
    const south = LatLng(54.7002, 25.3207);
    positions.add(south);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 650));
    final southHeading = tester.widget<Transform>(
      find.byKey(const Key('pilot-location-heading')),
    );
    // The direction icon rotates 180° for southbound movement.
    expect(southHeading.transform.entry(0, 0), closeTo(-1, 0.01));

    // Heading changes with the next GPS fix rather than staying backward.
    const east = LatLng(54.7002, 25.3407);
    positions.add(east);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 650));
    final eastHeading = tester.widget<Transform>(
      find.byKey(const Key('pilot-location-heading')),
    );
    expect(eastHeading.transform.entry(0, 0), closeTo(0, 0.02));
    expect(eastHeading.transform.entry(1, 0), closeTo(1, 0.02));
  });

}
