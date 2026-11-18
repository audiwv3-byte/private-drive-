import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'passenger_demo.dart';
import 'passenger_orders_demo.dart';
import 'pilot_cabin.dart';
import 'pilot_passenger_chat_demo.dart';
import 'demo_trip_store.dart';
import 'demo_dispatcher_cabinet.dart';
import 'company_info.dart';
import 'remote_sync_demo.dart';
export 'passenger_demo.dart' show PassengerDemo;
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:latlong2/latlong.dart' show LatLng;

/// Deep-link to the native Waze app. No HTTPS browser fallback.
final Uri privateDriveWazeAppUri = Uri.parse('waze://');

/// Standalone offline simulator with an on-device persisted demo order.
class PrivateDriveDemo extends StatefulWidget {
  const PrivateDriveDemo({super.key, this.enableMapTiles = true});

  final bool enableMapTiles;

  @override
  State<PrivateDriveDemo> createState() => _PrivateDriveDemoState();
}

class _PrivateDriveDemoState extends State<PrivateDriveDemo> {
  final DemoTripStore _trip = DemoTripStore();
  StreamSubscription<Position>? _pilotLocationStream;
  bool _startingLocation = false;
  bool _restoringOrder = true;
  final SharedPreferencesAsync _orderPrefs = SharedPreferencesAsync();
  static const _orderKey = 'pd_offline_demo_order_v1';
  Future<void> _saveQueue = Future<void>.value();
  String? _lastSavedSnapshot;

  Future<void> _restoreOrder() async {
    try {
      final saved = await _orderPrefs.getString(_orderKey);
      if (mounted && saved != null && _trip.restorePersistedJson(saved)) {
        _lastSavedSnapshot = saved;
      }
    } catch (_) {
      // Failed local storage must not prevent opening the demo.
    } finally {
      if (mounted) {
        _trip.addListener(_persistOrder);
        setState(() => _restoringOrder = false);
      }
    }
  }

  void _persistOrder() {
    final snapshot = _trip.toPersistedJson();
    if (snapshot == null || snapshot == _lastSavedSnapshot) return;
    _lastSavedSnapshot = snapshot;
    _saveQueue = _saveQueue.then((_) async {
      try {
        await _orderPrefs.setString(_orderKey, snapshot);
      } catch (_) {
        // Demo stays functional even without device storage.
      }
    });
  }

  @override
  void initState() {
    super.initState();
    _trip.addListener(_onPilotShiftChanged);
    unawaited(_restoreOrder());
  }

  Future<void> _requestPilotLocation() async {
    if (!widget.enableMapTiles) return;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) return;
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (!mounted) return;
      if (_trip.pilotOnline) _onPilotShiftChanged();
    } catch (_) {
      // Android permissions are controlled by the user, not by demo code.
    }
  }

  void _onPilotShiftChanged() {
    if (!_trip.pilotOnline) {
      _pilotLocationStream?.cancel();
      _pilotLocationStream = null;
      return;
    }
    if (_pilotLocationStream == null && !_startingLocation &&
        widget.enableMapTiles) {
      unawaited(_startPilotLocation());
    }
  }

  Future<void> _startPilotLocation() async {
    if (_startingLocation || !mounted || !_trip.pilotOnline) return;
    _startingLocation = true;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) return;
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (!mounted || !_trip.pilotOnline ||
          permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) return;
      _pilotLocationStream = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high, distanceFilter: 5,
        ),
      ).listen((position) {
        if (mounted && _trip.pilotOnline) {
          _trip.updatePilotLocation(position.latitude, position.longitude);
        }
      }, onError: (Object _) {
        _pilotLocationStream?.cancel();
        _pilotLocationStream = null;
      });
    } catch (_) {
      // Never invent a GPS fix when Android location is unavailable.
    } finally {
      _startingLocation = false;
    }
  }

  @override
  void dispose() {
    _trip.removeListener(_onPilotShiftChanged);
    _trip.removeListener(_persistOrder);
    _pilotLocationStream?.cancel();
    _trip.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_restoringOrder) {
      return const Scaffold(body: Center(child: CircularProgressIndicator(
        key: Key('demo-order-restoring'))));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE · Демоверсия')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.verified_user_outlined,
                        size: 50, color: Color(0xFFDDC184)),
                    const SizedBox(height: 16),
                    const Text('Выбери тестовый интерфейс',
                        style: TextStyle(fontSize: 22)),
                    const SizedBox(height: 12),
                    const Text(
                      'Тестовые заявки сохраняются на этом устройстве. '
                      'Нет реальных заказов, платежей и сервера.',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 18),
                    AnimatedBuilder(
                      animation: _trip,
                      builder: (context, _) => Column(
                        children: [
                          Text(_trip.statusLabel,
                              key: const Key('shared-trip-status'),
                              textAlign: TextAlign.center),
                          if (_trip.trip != null)
                            Text('${_trip.trip!.from} → ${_trip.trip!.to}',
                                key: const Key('shared-trip-route'),
                                textAlign: TextAlign.center),

                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      key: const Key('open-passenger-preview'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => PassengerDemo(
                          enableMapTiles: widget.enableMapTiles,
                          tripStore: _trip,
                        ))),
                      icon: const Icon(Icons.person_outline),
                      label: const Text('Пассажир'),
                    ),
                    const SizedBox(height: 12),
                    if (_trip.trip != null) ...[
                      OutlinedButton.icon(
                        key: const Key('open-my-orders'),
                        onPressed: () => Navigator.push(context,
                          MaterialPageRoute(builder: (_) =>
                            PassengerOrdersDemo(tripStore: _trip))),
                        icon: const Icon(Icons.receipt_long_outlined),
                        label: const Text('Мои заказы · управление'),
                      ),
                      const SizedBox(height: 12),
                    ],
                    FilledButton.icon(
                      key: const Key('open-dispatcher-preview'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => DemoDispatcherCabinet(
                          tripStore: _trip,
                          enableMapTiles: widget.enableMapTiles,
                        ))),
                      icon: const Icon(Icons.support_agent),
                      label: const Text('Кабинет диспетчера · демо'),
                    ),
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      key: const Key('open-remote-sync-demo'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const RemoteSyncDemo())),
                      icon: const Icon(Icons.sync_alt),
                      label: const Text('Тестовая связь между устройствами'),
                    ),
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      key: const Key('open-company-info'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(
                          builder: (_) => const CompanyInfoPage())),
                      icon: const Icon(Icons.info_outline),
                      label: const Text('О компании · Контакты · Соглашение'),
                    ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      key: const Key('open-pilot-preview'),
                      onPressed: () async {
                        // Request the normal Android foreground location
                        // permission on entering the pilot role.
                        await _requestPilotLocation();
                        if (!context.mounted) return;
                        Navigator.push(context,
                          MaterialPageRoute(builder: (_) => PilotCabin(
                          enableMapTiles: widget.enableMapTiles,
                          tripStore: _trip,
                        )));
                      },
                      icon: const Icon(Icons.navigation_outlined),
                      label: const Text('Кабина пилота'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Pilot-only foreground map; all trip controls change local demo state only.
/// In widget tests [enableMapTiles] is false: there are no tile HTTP requests.
class PilotDemo extends StatefulWidget {
  const PilotDemo({
    super.key,
    this.enableMapTiles = true,
    this.positions,
    this.tripStore,
    this.mapController,
    this.loadMapTiles = true,
    this.onIncomingSound,
    this.showAssignedOffer = true,
    this.testRoadPoints,
  });

  final bool enableMapTiles;
  /// Synthetic stream for deterministic tests; never enabled by production.
  final Stream<LatLng>? positions;
  final DemoTripStore? tripStore;
  /// Test-only injection; normal pilots use an internally owned controller.
  final MapController? mapController;
  /// Avoid network requests when exercising the real map camera in widget tests.
  final bool loadMapTiles;
  /// Test hook; production demo uses a local device notification sound.
  final VoidCallback? onIncomingSound;
  /// The premium cockpit renders this offer in the root overlay instead.
  final bool showAssignedOffer;
  /// Synthetic route fixture for widget tests only; never used by app UI.
  final List<LatLng>? testRoadPoints;

  @override
  State<PilotDemo> createState() => _PilotDemoState();
}

class _PilotDemoState extends State<PilotDemo> with SingleTickerProviderStateMixin {
  late final MapController _map = widget.mapController ?? MapController();
  StreamSubscription<Position>? _gps;
  StreamSubscription<LatLng>? _synthetic;
  LatLng? _position;
  LatLng? _displayPosition;
  double _headingDegrees = 0;
  bool _nightMap = false;
  late List<LatLng> _pickupRoadPoints = widget.testRoadPoints ?? const [];
  bool _pickupRouteAttempted = false;
  String _pickupRoutingInfo = '';
  int _pickupRouteGeneration = 0;

  Future<void> _loadPickupRoadRoute() async {
    if (!mounted || !_navigatingActiveTrip || _pickupRouteAttempted) return;
    final from = _position;
    final to = _pickupPreviewPoint;
    if (from == null || to == null || !widget.enableMapTiles ||
        !widget.loadMapTiles) return;
    _pickupRouteAttempted = true;
    final generation = ++_pickupRouteGeneration;
    setState(() {
      _pickupRoutingInfo = 'Построение маршрута по дорогам…';
    });
    HttpClient? client;
    try {
      client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 5);
      final uri = Uri.https('router.project-osrm.org',
        '/route/v1/driving/${from.longitude},${from.latitude};'
        '${to.longitude},${to.latitude}',
        {'overview': 'full', 'geometries': 'geojson'});
      final request = await client.getUrl(uri)
          .timeout(const Duration(seconds: 7));
      final response = await request.close()
          .timeout(const Duration(seconds: 7));
      if (response.statusCode != 200) {
        throw const HttpException('Routing unavailable');
      }
      final decoded = jsonDecode(await utf8.decoder.bind(response).join()
          .timeout(const Duration(seconds: 7))) as Map<String, dynamic>;
      final routes = decoded['routes'] as List<dynamic>?;
      if (routes == null || routes.isEmpty) {
        throw const FormatException('No road route');
      }
      final coordinates =
          ((routes.first as Map<String, dynamic>)['geometry']
            as Map<String, dynamic>)['coordinates'] as List<dynamic>;
      final points = coordinates.map((raw) {
        final pair = raw as List<dynamic>;
        return LatLng((pair[1] as num).toDouble(),
          (pair[0] as num).toDouble());
      }).toList(growable: false);
      if (!mounted || generation != _pickupRouteGeneration ||
          !_navigatingActiveTrip || points.length < 2) return;
      setState(() {
        _pickupRoadPoints = points;
        _pickupRoutingInfo = 'Дорожный маршрут · демонстрационный сервис';
      });
      _map.fitCamera(CameraFit.bounds(
        bounds: LatLngBounds.fromPoints([from, to]),
        padding: const EdgeInsets.all(72),
      ));
    } catch (_) {
      if (mounted && generation == _pickupRouteGeneration &&
          _navigatingActiveTrip) {
        setState(() => _pickupRoutingInfo =
          'Дорожный маршрут недоступен · проверь интернет и GPS');
      }
    } finally {
      client?.close(force: true);
    }
  }

  bool _incomingOffer = false;
  bool _nextAccepted = false;

  bool get _isUnderway => widget.tripStore?.status == DemoTripStatus.underway;

  void _simulateNewOffer() {
    if (!_isUnderway || _incomingOffer || _nextAccepted) return;
    setState(() => _incomingOffer = true);
    if (widget.onIncomingSound != null) {
      widget.onIncomingSound!();
    } else {
      SystemSound.play(SystemSoundType.alert);
    }
  }

  void _respondToOffer(bool accept) {
    if (!_isUnderway || !_incomingOffer) return;
    setState(() {
      _incomingOffer = false;
      if (accept) _nextAccepted = true;
    });
  }

  bool get _hasAssignedPassenger => widget.tripStore != null &&
      (widget.tripStore!.pilotAccepted &&
       (widget.tripStore!.status == DemoTripStatus.assigned ||
       widget.tripStore!.status == DemoTripStatus.approaching ||
       widget.tripStore!.status == DemoTripStatus.underway));

  void _openPassengerChat() {
    if (!_hasAssignedPassenger) return;
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => PilotPassengerChatDemo(
        messages: [
          ...widget.tripStore!.pilotChatMessages,
          ...widget.tripStore!.passengerChatMessages.map(
            (message) => 'Пассажир: $message'),
        ],
        onSend: (text) {
          if (!_hasAssignedPassenger) return;
          widget.tripStore!.addPilotChatMessage(text);
        },
      ),
    ));
  }

  /// Launch Waze as a separate Android application (never in an in-app
  /// browser or WebView). Do not fallback to HTTPS: that may open inside PD.
  /// The demo has no verified destination coordinates yet.
  Future<void> _openWaze() async {
    try {
      final opened = await launchUrl(
        privateDriveWazeAppUri,
        mode: LaunchMode.externalApplication,
      );
      if (!opened && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Установи Waze: открыть его отдельно не удалось.')),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Установи Waze: открыть его отдельно не удалось.')),
        );
      }
    }
  }

  void _showCallDemo() {
    if (!_hasAssignedPassenger) return;
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Позвонить пассажиру'),
        content: const Text(
          'Это локальная демоверсия. Подтверждённого номера пассажира нет. '
          'Реальный звонок не выполняется.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Понятно'),
          ),
        ],
      ),
    );
  }
  late final AnimationController _cameraAnimation = AnimationController(
    vsync: this, duration: const Duration(milliseconds: 600),
  )..addListener(_animatePosition);
  LatLng? _animationStart;
  LatLng? _animationTarget;
  bool _gpsEnabled = false;
  String _gpsMessage = 'GPS выключен';
  int stage = 0;
  bool paused = false;
  static const stages = ['К пассажиру', 'В путь', 'Завершить'];
  static const labels = ['Нет активной поездки', 'Едем к пассажиру', 'Поездка выполняется'];
  static const vilnius = LatLng(54.6872, 25.2797);
  // These are city landmarks, NOT verified passenger pickup addresses.
  static const _demoCityCenters = <String, LatLng>{
    'вильнюс': LatLng(54.6872, 25.2797),
    'каунас': LatLng(54.8985, 23.9036),
    'клайпеда': LatLng(55.7033, 21.1443),
    'паланга': LatLng(55.9175, 21.0686),
    'варшава': LatLng(52.2297, 21.0122),
    'тракай': LatLng(54.6389, 24.9342),
    'аэропорт вильнюса': LatLng(54.6341, 25.2858),
  };

  bool get _approachingPassenger =>
      widget.tripStore?.status == DemoTripStatus.approaching;

  bool get _navigatingActiveTrip =>
      widget.tripStore?.status == DemoTripStatus.approaching ||
      widget.tripStore?.status == DemoTripStatus.underway;

  String? get _pickupAddress => _navigatingActiveTrip
      ? (_approachingPassenger
          ? widget.tripStore?.trip?.from
          : widget.tripStore?.trip?.to)
      : null;

  LatLng? get _pickupPreviewPoint {
    final place = _pickupAddress?.trim().toLowerCase();
    return place == null ? null : _demoCityCenters[place];
  }

  void _focusPickupPreview() {
    final point = _pickupPreviewPoint;
    if (!mounted || !widget.enableMapTiles || point == null) return;
    // A city-centre hint is a visual preview, not a street navigation route.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_approachingPassenger) return;
      final pilot = _displayPosition;
      if (pilot == null) {
        _map.move(point, 13);
      } else {
        _map.fitCamera(CameraFit.bounds(
          bounds: LatLngBounds.fromPoints([pilot, point]),
          padding: const EdgeInsets.all(90),
        ));
      }
    });
  }

  @override
  void initState() {
    super.initState();
    widget.tripStore?.addListener(_onTripChanged);
    if (widget.tripStore?.pilotOnline == true) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _onTripChanged();
      });
    }
  }

  void _onTripChanged() {
    if (!mounted) return;
    final store = widget.tripStore;
    final lat = store?.pilotLatitude;
    final lng = store?.pilotLongitude;
    if (store?.pilotOnline == true && lat != null && lng != null &&
        (_position == null ||
         _position!.latitude != lat || _position!.longitude != lng)) {
      _gpsEnabled = true;
      _onPosition(LatLng(lat, lng), publishToStore: false);
    } else {
      setState(() {});
    }
  }

  String get _tripLabel => widget.tripStore?.statusLabel ??
      (paused ? 'Остановка · демо' : labels[stage]);

  String get _actionText {
    final store = widget.tripStore;
    if (store == null) return stages[stage];
    return switch (store.status) {
      DemoTripStatus.assigned => 'К пассажиру',
      DemoTripStatus.approaching => 'В путь',
      DemoTripStatus.underway => 'Завершить',
      _ => 'Нет назначенной поездки',
    };
  }

  bool get _canAdvance {
    final store = widget.tripStore;
    if (store == null) return !paused;
    return !store.paused &&
      ((store.status == DemoTripStatus.assigned && store.pilotAccepted) ||
       store.status == DemoTripStatus.approaching ||
       store.status == DemoTripStatus.underway);
  }

  bool get _canPause {
    final store = widget.tripStore;
    if (store == null) return stage != 0;
    return store.status == DemoTripStatus.approaching ||
        store.status == DemoTripStatus.underway;
  }


  void _animatePosition() {
    if (!mounted || _animationStart == null || _animationTarget == null) return;
    final progress = Curves.easeOutCubic.transform(_cameraAnimation.value);
    final from = _animationStart!;
    final to = _animationTarget!;
    final current = LatLng(
      from.latitude + (to.latitude - from.latitude) * progress,
      from.longitude + (to.longitude - from.longitude) * progress,
    );
    setState(() => _displayPosition = current);
    if (widget.enableMapTiles) _map.move(current, _map.camera.zoom);
  }

  void _onPosition(LatLng value, {double? sensorHeading, double? speed,
      bool publishToStore = true}) {
    if (!mounted || !value.latitude.isFinite || !value.longitude.isFinite ||
        value.latitude.abs() > 90 || value.longitude.abs() > 180) return;
    final previous = _displayPosition;
    final previousFix = _position;
    // The location icon points north by default. Rotate it clockwise to the
    // vehicle's course rather than leaving it fixed when heading south/west.
    // Ignore heading jitter while standing still.
    double? course;
    if (speed != null && speed >= 1.5 &&
        sensorHeading != null && sensorHeading.isFinite &&
        sensorHeading >= 0 && sensorHeading < 360) {
      course = sensorHeading;
    } else if (previousFix != null &&
        Geolocator.distanceBetween(
          previousFix.latitude, previousFix.longitude,
          value.latitude, value.longitude,
        ) >= 5) {
      course = Geolocator.bearingBetween(
        previousFix.latitude, previousFix.longitude,
        value.latitude, value.longitude,
      );
    }
    setState(() {
      _position = value;
      if (course != null) _headingDegrees = (course + 360) % 360;
      _gpsMessage = 'GPS активен · только на устройстве';
    });
    if (publishToStore) {
      widget.tripStore?.updatePilotLocation(value.latitude, value.longitude);
    }
    if (_navigatingActiveTrip && !_pickupRouteAttempted) {
      unawaited(_loadPickupRoadRoute());
    }
    // First GPS fix centers immediately; later fixes interpolate both the
    // navigation marker and camera. A new fix starts at the current animation
    // position rather than jumping to the previous target.
    if (previous == null) {
      setState(() => _displayPosition = value);
      if (widget.enableMapTiles) _map.move(value, _map.camera.zoom);
      return;
    }
    _cameraAnimation.stop();
    _animationStart = previous;
    _animationTarget = value;
    _cameraAnimation.forward(from: 0);
  }

  Future<void> _enableGps() async {
    if (_gpsEnabled) return;
    // Synthetic positions never request platform permissions or network calls.
    if (widget.positions != null) {
      setState(() {
        _gpsEnabled = true;
        _gpsMessage = 'Тестовый GPS';
      });
      _synthetic = widget.positions!.listen(_onPosition);
      return;
    }
    if (!widget.enableMapTiles) return;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        if (mounted) setState(() => _gpsMessage = 'Включи геолокацию устройства');
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        if (mounted) setState(() => _gpsMessage = 'Доступ к GPS не предоставлен');
        return;
      }
      if (!mounted) return;
      setState(() {
        _gpsEnabled = true;
        _gpsMessage = 'Ожидание координат GPS…';
      });
      _gps = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 5,
        ),
      ).listen(
        (p) => _onPosition(
          LatLng(p.latitude, p.longitude),
          sensorHeading: p.heading,
          speed: p.speed,
        ),
        onError: (Object error) {
          if (mounted) setState(() => _gpsMessage = 'GPS недоступен');
        },
      );
    } catch (_) {
      if (mounted) setState(() => _gpsMessage = 'GPS недоступен');
    }
  }

  void _stopGps() {
    _gps?.cancel();
    _gps = null;
    _synthetic?.cancel();
    _synthetic = null;
    _cameraAnimation.stop();
    _animationStart = null;
    _animationTarget = null;
    setState(() {
      _displayPosition = null;
      _headingDegrees = 0;
      _gpsEnabled = false;
      _gpsMessage = 'GPS выключен';
      _position = null;
    });
  }

  void advance() {
    if (widget.tripStore != null) {
      final changed = widget.tripStore!.advancePilot();
      if (changed && _approachingPassenger) {
        _pickupRouteAttempted = false;
        _pickupRoadPoints = const [];
        _focusPickupPreview();
        unawaited(_loadPickupRoadRoute());
      } else if (changed && _isUnderway) {
        // New phase of the SAME trip: target changes from pickup to drop-off.
        // Keep the current polyline on screen while the new road route loads.
        ++_pickupRouteGeneration;
        _pickupRouteAttempted = false;
        _pickupRoutingInfo = 'Маршрут к месту назначения обновляется…';
        unawaited(_loadPickupRoadRoute());
      } else if (changed && widget.tripStore?.status ==
          DemoTripStatus.finished) {
        ++_pickupRouteGeneration;
        _pickupRoadPoints = const [];
        _pickupRoutingInfo = '';
      }
      return;
    }
    setState(() {
      if (stage == 2) {
        stage = 0;
        paused = false;
      } else {
        stage++;
      }
    });
  }

  @override
  void dispose() {
    widget.tripStore?.removeListener(_onTripChanged);
    _gps?.cancel();
    _synthetic?.cancel();
    _cameraAnimation.dispose();
    if (widget.mapController == null) _map.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [
          if (widget.enableMapTiles)
            FlutterMap(
              key: const Key('pilot-map-surface'),
              mapController: _map,
              options: const MapOptions(
                initialCenter: vilnius,
                initialZoom: 14,
              ),
              children: [
                if (widget.loadMapTiles)
                  ColorFiltered(
                    colorFilter: _nightMap
                        ? const ColorFilter.matrix(<double>[
                            -0.78, 0, 0, 0, 211,
                            0, -0.78, 0, 0, 211,
                            0, 0, -0.78, 0, 211,
                            0, 0, 0, 1, 0,
                          ])
                        : const ColorFilter.mode(
                            Colors.transparent, BlendMode.dst),
                    child: TileLayer(
                      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'lt.privatedrive.privateDrive',
                      maxNativeZoom: 19,
                    ),
                  ),
                if (_navigatingActiveTrip && _pickupRoadPoints.isNotEmpty)
                  PolylineLayer(
                    key: const Key('pilot-road-route'),
                    polylines: [
                      Polyline(
                        points: _pickupRoadPoints,
                        strokeWidth: 5,
                        color: const Color(0xFFDDC184),
                      ),
                    ],
                  ),
                if (_navigatingActiveTrip && _pickupPreviewPoint != null)
                  MarkerLayer(markers: [
                    Marker(
                      point: _pickupPreviewPoint!,
                      width: 52,
                      height: 54,
                      child: const Icon(
                        Icons.location_on,
                        key: Key('pilot-pickup-preview-pin'),
                        size: 48,
                        color: Color(0xFFDDC184),
                        shadows: [Shadow(color: Colors.black, blurRadius: 5)],
                      ),
                    ),
                  ]),
                if (_displayPosition != null)
                  MarkerLayer(markers: [
                    Marker(
                      point: _displayPosition!,
                      width: 48,
                      height: 48,
                      child: Transform.rotate(
                        key: const Key('pilot-location-heading'),
                        angle: _headingDegrees * math.pi / 180,
                        child: const Stack(
                          alignment: Alignment.center,
                          children: [
                            Icon(
                              Icons.directions_car_filled,
                              size: 46,
                              color: Color(0xFFFFDC91),
                              shadows: [
                                Shadow(color: Colors.black, blurRadius: 9),
                              ],
                            ),
                            Icon(
                              Icons.directions_car_filled,
                              key: Key('pilot-location-marker'),
                              size: 36,
                              color: Color(0xFF172B3F),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ]),
                const RichAttributionWidget(
                  attributions: [
                    TextSourceAttribution('© OpenStreetMap contributors'),
                  ],
                ),
              ],
            )
          else
            const RepaintBoundary(
              child: CustomPaint(
                key: Key('pilot-map-surface'),
                painter: DemoMapPainter(),
              ),
            ),
          SafeArea(
            child: Stack(
              children: [
                Positioned(
                  top: 8,
                  left: 12,
                  child: IconButton.filledTonal(
                    key: const Key('exit-pilot-preview'),
                    tooltip: 'Назад',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.arrow_back),
                  ),
                ),
                Positioned(
                  top: 64,
                  left: 12,
                  child: OutlinedButton(
                    key: const Key('pilot-open-waze'),
                    onPressed: _openWaze,
                    style: OutlinedButton.styleFrom(
                      backgroundColor: const Color(0x660E1624),
                      foregroundColor: Colors.white,
                      side: const BorderSide(color: Color(0x99DDC184)),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 10,
                      ),
                    ),
                    child: const Text('Waze',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                  ),
                ),
                Positioned(
                  top: 120,
                  left: 12,
                  child: Material(
                    color: const Color(0xE8172535),
                    borderRadius: BorderRadius.circular(14),
                    child: IconButton(
                      key: const Key('pilot-map-day-night'),
                      tooltip: _nightMap ? 'Дневная карта' : 'Ночная карта',
                      icon: Icon(_nightMap ? Icons.wb_sunny_outlined
                        : Icons.dark_mode_outlined,
                        color: const Color(0xFFDDC184), size: 22),
                      onPressed: () => setState(() => _nightMap = !_nightMap),
                    ),
                  ),
                ),
                Positioned(
                  top: 8,
                  right: 12,
                  child: Chip(
                    key: const Key('pilot-gps-status'),
                    label: Text(widget.tripStore != null
                      ? (widget.tripStore!.pilotLatitude != null
                        ? 'GPS активен · демо'
                        : (widget.tripStore!.pilotOnline
                            ? 'GPS: ожидание разрешения/координат'
                            : 'GPS выключен · не на линии'))
                      : _gpsMessage),
                  ),
                ),
                if (_displayPosition != null && !widget.enableMapTiles)
                  const Center(
                    child: Icon(Icons.navigation, size: 44,
                        color: Color(0xFF00CCFF),
                        shadows: [Shadow(color: Colors.black, blurRadius: 8)]),
                  ),
                if (widget.tripStore == null)
                  Positioned(
                    top: 60,
                    right: 12,
                    child: Column(
                    children: [
                      if (!_gpsEnabled)
                        FloatingActionButton.small(
                          key: const Key('pilot-enable-gps'),
                          heroTag: 'pilot-gps',
                          tooltip: 'Включить GPS',
                          onPressed: _enableGps,
                          child: const Icon(Icons.my_location),
                        )
                      else
                        FloatingActionButton.small(
                          key: const Key('pilot-disable-gps'),
                          heroTag: 'pilot-stop-gps',
                          tooltip: 'Выключить GPS',
                          onPressed: _stopGps,
                          child: const Icon(Icons.location_off),
                        ),
                      if (_gpsEnabled && _position != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: FloatingActionButton.small(
                            key: const Key('pilot-center-map'),
                            heroTag: 'pilot-center',
                            tooltip: 'Центрировать карту',
                            onPressed: () {
                              if (widget.enableMapTiles) {
                                _map.move(_position!, _map.camera.zoom);
                              }
                            },
                            child: const Icon(Icons.gps_fixed),
                          ),
                        ),
                    ],
                  ),
                ),
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 20),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: const Color(0xE9111111),
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(_tripLabel,
                                key: const Key('pilot-trip-state')),
                            if (_navigatingActiveTrip) ...[
                              if (_pickupRoutingInfo.isNotEmpty)
                                Text(_pickupRoutingInfo,
                                  key: const Key('pilot-routing-status'),
                                  style: const TextStyle(
                                    fontSize: 11, color: Colors.white70)),

                              const SizedBox(height: 6),
                              Text('${_approachingPassenger ? 'Подача' : 'Назначение'}: ${_pickupAddress ?? "адрес не указан"}',
                                  key: const Key('pilot-pickup-address'),
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    color: Color(0xFFDDC184),
                                    fontWeight: FontWeight.w700,
                                  )),
                              Text(
                                _pickupPreviewPoint != null
                                  ? 'Метка обозначает только центр города · '
                                    '${_approachingPassenger ? 'точный адрес подачи не указан' : 'точный адрес назначения не указан'}'
                                  : 'Точка подачи не определена · '
                                    'требуется геокодирование адреса',
                                key: const Key('pilot-pickup-accuracy'),
                                textAlign: TextAlign.center,
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: Colors.white70,
                                ),
                              ),
                            ],
                            if (widget.showAssignedOffer &&
                                widget.tripStore?.status == DemoTripStatus.assigned &&
                                widget.tripStore?.pilotAccepted == false)
                              Container(
                                key: const Key('pilot-assigned-offer'),
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: const Color(0xFF22252A),
                                  border: Border.all(color: const Color(0xFFDDC184)),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    const Text('Новый назначенный заказ · демо',
                                      style: TextStyle(
                                        color: Color(0xFFDDC184),
                                        fontWeight: FontWeight.bold,
                                      )),
                                    const SizedBox(height: 6),
                                    Text(
                                      '${widget.tripStore!.trip!.from} → ${widget.tripStore!.trip!.to}',
                                      key: const Key('pilot-assigned-route'),
                                      textAlign: TextAlign.center,
                                    ),
                                    const SizedBox(height: 10),
                                    Row(children: [
                                      Expanded(
                                        child: FilledButton(
                                          key: const Key('pilot-accept-assigned'),
                                          onPressed: widget.tripStore!.acceptAssignedPilot,
                                          child: const Text('Принять'),
                                        ),
                                      ),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: OutlinedButton(
                                          key: const Key('pilot-decline-assigned'),
                                          onPressed: widget.tripStore!.declineAssignedPilot,
                                          child: const Text('Отклонить'),
                                        ),
                                      ),
                                    ]),
                                  ],
                                ),
                              ),
                            const SizedBox(height: 10),
                            if (_isUnderway && !_incomingOffer && !_nextAccepted)
                              OutlinedButton.icon(
                                key: const Key('pilot-simulate-offer'),
                                onPressed: _simulateNewOffer,
                                icon: const Icon(Icons.notifications_active_outlined),
                                label: const Text('Сымитировать новый заказ'),
                              ),
                            if (_isUnderway && _incomingOffer)
                              Container(
                                key: const Key('pilot-next-offer'),
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: const Color(0xFF232323),
                                  border: Border.all(color: const Color(0xFFDDC184)),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    const Text(
                                      'Новый заказ · демо',
                                      style: TextStyle(
                                        color: Color(0xFFDDC184),
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    const Text('Вильнюс → Аэропорт Вильнюса'),
                                    const SizedBox(height: 6),
                                    Row(
                                      children: [
                                        Expanded(
                                          child: FilledButton(
                                            key: const Key('pilot-accept-next'),
                                            style: FilledButton.styleFrom(
                                              backgroundColor: const Color(0xFF15844B),
                                            ),
                                            onPressed: () => _respondToOffer(true),
                                            child: const Text('Принять следующий'),
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Expanded(
                                          child: OutlinedButton(
                                            key: const Key('pilot-decline-next'),
                                            style: OutlinedButton.styleFrom(
                                              foregroundColor: const Color(0xFFFF6972),
                                            ),
                                            onPressed: () => _respondToOffer(false),
                                            child: const Text('Пропустить'),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            if (_nextAccepted)
                              const Text(
                                'Следующий заказ принят · демо',
                                key: Key('pilot-next-queued-status'),
                                style: TextStyle(color: Color(0xFF34E88A)),
                              ),
                            const SizedBox(height: 10),
                            if (_hasAssignedPassenger) ...[
                              const Align(
                                alignment: Alignment.centerLeft,
                                child: Text('Связь с пассажиром · демо'),
                              ),
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  Expanded(
                                    child: OutlinedButton.icon(
                                      key: const Key('pilot-passenger-chat'),
                                      onPressed: _openPassengerChat,
                                      icon: const Icon(Icons.chat_bubble_outline),
                                      label: const Text('Написать'),
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: OutlinedButton.icon(
                                      key: const Key('pilot-passenger-call'),
                                      onPressed: _showCallDemo,
                                      icon: const Icon(Icons.call_outlined),
                                      label: const Text('Позвонить'),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                            ],

                            Row(
                              children: [
                                Expanded(
                                  child: FilledButton(
                                    key: const Key('pilot-next-trip'),
                                    onPressed: _canAdvance ? advance : null,
                                    child: Text(_actionText),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                OutlinedButton(
                                  key: const Key('pilot-pause-trip'),
                                  onPressed: !_canPause ? null : () {
                                    if (widget.tripStore != null) {
                                      widget.tripStore!.togglePause();
                                    } else {
                                      setState(() => paused = !paused);
                                    }
                                  },
                                  child: Text((widget.tripStore?.paused ?? paused)
                                      ? 'Продолжить' : 'Остановка'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class DemoMapPainter extends CustomPainter {
  const DemoMapPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawColor(const Color(0xFF202A29), BlendMode.src);
    final blocks = Paint()..color = const Color(0xFF2B3933);
    final roads = Paint()
      ..color = const Color(0xFF68716A)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 14;
    final minorRoads = Paint()
      ..color = const Color(0xFF43544E)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 6;
    for (var i = 0; i < 9; i++) {
      final dx = size.width * i / 8;
      final dy = size.height * i / 8;
      canvas.drawRect(Rect.fromLTWH(dx - 12, dy - 20, 65, 90), blocks);
      canvas.drawLine(Offset(dx, 0), Offset(dx + size.width * 0.17, size.height), minorRoads);
      canvas.drawLine(Offset(0, dy), Offset(size.width, dy + size.height * 0.13), minorRoads);
    }
    final path = Path()
      ..moveTo(-30, size.height * 0.8)
      ..quadraticBezierTo(size.width * 0.45, size.height * 0.6, size.width * 0.35, -20);
    canvas.drawPath(path, roads);
  }

  @override
  bool shouldRepaint(covariant DemoMapPainter oldDelegate) => false;
}
