import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';

import 'package:private_drive/demo_interfaces.dart' show PilotDemo;
import 'package:private_drive/native_pilot_orders.dart';
import 'package:private_drive/pilot_cabin.dart';

const _id = '05cdbc84-0930-4c52-baa1-149a03190d78';

class _AssignmentApi extends NativePilotOrdersApi {
  _AssignmentApi() : super(baseUrl: NativePilotOrdersApi.stage, token: '');

  int reads = 0;

  @override
  Future<List<PilotAssignedOrder>> load() async {
    reads++;
    return const [
      PilotAssignedOrder(
        orderId: _id,
        origin: 'Исходная точка теста',
        destination: 'Пункт назначения теста',
        date: '2026-12-03',
        time: '14:30',
        status: 'assigned',
      ),
    ];
  }
}

class _LocationPlatform extends GeolocatorPlatform {
  _LocationPlatform() {
    positions = StreamController<Position>.broadcast(
      onListen: () => starts++,
      onCancel: () => cancellations++,
    );
  }

  late final StreamController<Position> positions;
  int starts = 0;
  int cancellations = 0;
  LocationPermission permission = LocationPermission.whileInUse;
  Completer<LocationPermission>? waitingPermission;
  int permissionRequests = 0;
  VoidCallback? beforePermissionCheck;
  VoidCallback? beforePositionStream;

  @override
  Future<bool> isLocationServiceEnabled() async {
    beforePermissionCheck?.call();
    return true;
  }

  @override
  Future<LocationPermission> checkPermission() async => permission;

  @override
  Future<LocationPermission> requestPermission() {
    permissionRequests++;
    return waitingPermission!.future;
  }

  @override
  Stream<Position> getPositionStream({LocationSettings? locationSettings}) {
    beforePositionStream?.call();
    return positions.stream;
  }

  void fix({
    bool mocked = false,
    double latitude = 54.689,
    double longitude = 25.28,
  }) {
    positions.add(
      Position(
        latitude: latitude,
        longitude: longitude,
        timestamp: DateTime.utc(2026, 12, 3),
        accuracy: 3,
        altitude: 0,
        altitudeAccuracy: 1,
        heading: 5,
        headingAccuracy: 4,
        speed: 5,
        speedAccuracy: 1,
        isMocked: mocked,
      ),
    );
  }
}

_LocationPlatform _mockLocationPlatform() {
  final old = GeolocatorPlatform.instance;
  final mock = _LocationPlatform();
  GeolocatorPlatform.instance = mock;
  addTearDown(() async {
    GeolocatorPlatform.instance = old;
    await mock.positions.close();
  });
  return mock;
}

class _RecordingTiles extends TileProvider {
  _RecordingTiles(this.urls);
  final List<Uri> urls;

  static final _pixel = MemoryImage(
    base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=',
    ),
  );

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) {
    urls.add(Uri.parse(getTileUrl(coordinates, options)));
    return _pixel;
  }
}

void main() {
  testWidgets(
    'assigned pilot opens existing map without demo actions and returns to the same order',
    (tester) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      final assignments = _AssignmentApi();
      await tester.pumpWidget(
        MaterialApp(
          home: PilotCabin(assignmentApi: assignments, enableMapTiles: false),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('ID заказа: $_id'), findsOneWidget);
      expect(find.byKey(const Key('pilot-connected-brand-logo')), findsOneWidget);
      expect(find.byKey(const Key('pilot-connected-cabin-title')), findsOneWidget);
      expect(find.byKey(const Key('pilot-offline-vilnius-background')), findsOneWidget);
      expect(find.byKey(const Key('pilot-power-toggle')), findsNothing,
          reason: 'Never display demo online status in connected cabin');
      expect(assignments.reads, 1);

      await tester.tap(find.byKey(const Key('pilot-server-open-map')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
      expect(find.byKey(const Key('pilot-map-day-night')), findsOneWidget);
      expect(find.byTooltip('Показать мою позицию'), findsOneWidget);
      expect(find.text('Позиция диспетчеру не передаётся'), findsOneWidget);
      for (final key in [
        'pilot-open-drawer',
        'pilot-open-waze',
        'pilot-next-trip',
        'pilot-pause-trip',
        'pilot-assigned-offer',
        'pilot-passenger-chat',
        'pilot-trip-state',
        'pilot-drawer-remote-chat',
        'pilot-drawer-cash-settings',
      ]) {
        expect(find.byKey(Key(key)), findsNothing);
      }
      expect(find.byKey(const Key('pilot-location-marker')), findsNothing);

      await tester.pump(const Duration(seconds: 30));
      expect(assignments.reads, 1, reason: 'No order polling behind the map');
      await tester.tap(find.byKey(const Key('exit-pilot-preview')));
      await tester.pumpAndSettle();
      expect(find.text('ID заказа: $_id'), findsOneWidget);
      expect(find.text('2026-12-03 14:30 · Назначен'), findsOneWidget);
      expect(
        assignments.reads,
        2,
        reason: 'Fresh server order when list returns',
      );
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'own position requires opt-in, clears on pause and stops again on exit',
    (tester) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      final location = _mockLocationPlatform();
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) {
              return Scaffold(
                body: TextButton(
                  onPressed: () => Navigator.of(context).push<void>(
                    MaterialPageRoute<void>(
                      builder: (_) =>
                          const PilotDemo.ownDevice(loadMapTiles: false),
                    ),
                  ),
                  child: const Text('Открыть карту'),
                ),
              );
            },
          ),
        ),
      );
      await tester.tap(find.text('Открыть карту'));
      await tester.pumpAndSettle();
      location.fix();
      await tester.pump();
      expect(location.starts, 0);
      const marker = Key('pilot-location-marker');
      expect(find.byKey(marker), findsNothing);

      await tester.tap(find.byTooltip('Показать мою позицию'));
      await tester.pump();
      expect(location.starts, 1);
      expect(find.byKey(marker), findsNothing, reason: 'No marker until a fix');
      location.fix();
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsOneWidget);
      expect(
        find.text('Моя позиция · не передаётся диспетчеру'),
        findsOneWidget,
      );

      location.fix(latitude: 54.691);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsNothing);
      expect(location.cancellations, 1);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      location.fix(latitude: 54.691);
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsNothing);
      expect(location.starts, 1, reason: 'Resume is not a new opt-in');

      await tester.tap(find.byTooltip('Показать мою позицию'));
      await tester.pump();
      expect(location.starts, 2);
      location.fix(latitude: 54.691);
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsOneWidget);
      await tester.tap(find.byKey(const Key('pilot-disable-gps')));
      await tester.pumpAndSettle();
      expect(location.cancellations, 2);
      expect(find.byKey(marker), findsNothing);

      await tester.tap(find.byTooltip('Показать мою позицию'));
      await tester.pump();
      await tester.tap(find.byKey(const Key('exit-pilot-preview')));
      await tester.pumpAndSettle();
      expect(location.starts, 3);
      expect(location.cancellations, 3);
      expect(find.byKey(marker), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'permission completed after pause cannot start GPS; mock fixes do not display',
    (tester) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      final location = _mockLocationPlatform()
        ..permission = LocationPermission.denied
        ..waitingPermission = Completer<LocationPermission>();
      await tester.pumpWidget(
        const MaterialApp(home: PilotDemo.ownDevice(loadMapTiles: false)),
      );
      final enable = find.byTooltip('Показать мою позицию');
      await tester.tap(enable);
      await tester.pump();
      expect(location.permissionRequests, 1);
      expect(location.starts, 0);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      location.permission = LocationPermission.whileInUse;
      location.waitingPermission!.complete(location.permission);
      await tester.pumpAndSettle();
      expect(
        location.starts,
        0,
        reason: 'The old permission request is no longer active',
      );
      expect(find.text('Нажми «Показать мою позицию» снова'), findsOneWidget);

      await tester.tap(enable);
      await tester.pump();
      expect(location.starts, 1);
      location.fix(mocked: true);
      await tester.pumpAndSettle();
      const marker = Key('pilot-location-marker');
      expect(find.byKey(marker), findsNothing);
      location.fix();
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      expect(location.cancellations, 1);
    },
  );
  testWidgets(
    'online OSM requests never follow device fixes and resume an ordinary map viewport',
    (tester) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      final location = _mockLocationPlatform();
      final urls = <Uri>[];
      final debugMessages = <String>[];
      final oldPrint = debugPrint;
      debugPrint = (String? text, {int? wrapWidth}) {
        if (text != null) debugMessages.add(text);
      };
      addTearDown(() => debugPrint = oldPrint);
      const map = Key('pilot-map-surface');
      const grid = Key('pilot-device-position-grid');
      const marker = Key('pilot-location-marker');

      await tester.pumpWidget(
        MaterialApp(
          home: PilotDemo.ownDevice(
            deviceTileProviderForTest: () => _RecordingTiles(urls),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(map), findsOneWidget);
      expect(find.byType(TileLayer), findsOneWidget);
      expect(urls, isNotEmpty);
      expect(urls.every((url) => url.host == 'tile.openstreetmap.org'), isTrue);
      final beforePan = urls.length;
      await tester.dragFrom(const Offset(400, 250), const Offset(400, 45));
      await tester.pumpAndSettle();
      expect(
        urls.length,
        greaterThan(beforePan),
        reason: 'Online map still pans manually',
      );
      final afterPan = urls.length;
      final manualViewports = urls.toSet();
      location.beforePermissionCheck = location.beforePositionStream = () {
        expect(find.byType(TileLayer), findsNothing);
        expect(find.byKey(grid), findsOneWidget);
        expect(urls.length, afterPan);
      };

      await tester.tap(find.byTooltip('Показать мою позицию'));
      await tester.pumpAndSettle();
      expect(location.starts, 1);
      expect(find.byType(TileLayer), findsNothing);
      expect(find.byKey(grid), findsOneWidget);
      location.fix(mocked: true, latitude: 35.12345, longitude: -120.34567);
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsNothing);

      location.fix(latitude: 35.12345, longitude: -120.34567);
      await tester.pumpAndSettle();
      expect(find.byKey(marker), findsOneWidget);
      expect(find.text('35.12345, -120.34567'), findsOneWidget);
      location.fix(latitude: -33.45678, longitude: 151.56789);
      await tester.pumpAndSettle();
      expect(find.text('-33.45678, 151.56789'), findsOneWidget);
      expect(find.byKey(const Key('pilot-center-map')), findsNothing);
      expect(
        urls.length,
        afterPan,
        reason: 'No URLs after any physical or mock fix',
      );
      expect(
        debugMessages.any(
          (line) =>
              line.contains('35.12345') ||
              line.contains('151.56789') ||
              line.contains('PD_PILOT_TILE_ERROR'),
        ),
        isFalse,
      );

      await tester.tap(find.byKey(const Key('pilot-disable-gps')));
      await tester.pumpAndSettle();
      expect(location.cancellations, 1);
      expect(find.byKey(map), findsOneWidget);
      expect(find.byType(TileLayer), findsOneWidget);
      expect(find.byKey(grid), findsNothing);
      expect(find.byKey(marker), findsNothing);
      expect(
        urls.length,
        greaterThan(afterPan),
        reason: 'Only the normal map resumes',
      );
      expect(urls.skip(afterPan).every(manualViewports.contains), isTrue);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
