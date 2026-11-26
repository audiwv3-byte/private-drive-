import 'dart:async';
import 'native_orders_api.dart';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb, TargetPlatform;
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'passenger_ride_entry.dart';
import 'app_language.dart';
import 'passenger_orders_demo.dart';
import 'pilot_cabin.dart';
import 'pilot_identity_api.dart';
import 'pilot_identity_review_page.dart';
import 'pilot_sound_settings.dart';
import 'pilot_payment_settings.dart';
import 'pilot_offer_tone.dart';
import 'pd_slide_to_confirm.dart';
import 'pilot_passenger_chat_demo.dart';
import 'isolated_trip_chat.dart';
import 'message_voice.dart';
import 'demo_trip_store.dart';
import 'demo_dispatcher_cabinet.dart';
import 'company_info.dart';
import 'remote_sync_demo.dart';
import 'pd_http_api.dart';
export 'passenger_demo.dart' show PassengerDemo;
import 'package:flutter_map/flutter_map.dart';
import 'demo_map_tile_provider.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:latlong2/latlong.dart' show LatLng;

/// Deep-link to the native Waze app. No HTTPS browser fallback.
final Uri privateDriveWazeAppUri = Uri.parse('waze://');

/// Standalone offline simulator with an on-device persisted demo order.
class PrivateDriveDemo extends StatefulWidget {
  const PrivateDriveDemo({
    super.key,
    this.enableMapTiles = true,
    this.passengerOnly = false,
    this.adminOnly = false,
    this.pilotOnly = false,
    this.storageScope,
    this.ordersApi,
    this.onSignOut,
    this.onBackToCabinets,
  });

  final bool enableMapTiles;
  /// Only the passenger cabin is reachable after a verified public SMS login.
  /// The multi-role demo hub stays exclusive to offline development preview.
  final bool passengerOnly;
  /// Accessible only when a trusted SMS server returns an administrator role.
  /// This is a local demo console; real admin API authorization is separate.
  final bool adminOnly;
  final bool pilotOnly;
  final String? storageScope;
  final NativeOrdersApi? ordersApi;
  final VoidCallback? onSignOut;
  final VoidCallback? onBackToCabinets;

  @override
  State<PrivateDriveDemo> createState() => _PrivateDriveDemoState();
}

class _PrivateDriveDemoState extends State<PrivateDriveDemo> with WidgetsBindingObserver {
  final DemoTripStore _trip = DemoTripStore();
  StreamSubscription<Position>? _pilotLocationStream;
  Timer? _pilotGpsRetry;
  bool _startingLocation = false;
  bool _appInForeground = true;
  bool _restoringOrder = true;
  SharedPreferencesAsync? _orderPrefs;

  SharedPreferencesAsync? _openOrderPrefs() {
    try {
      return SharedPreferencesAsync();
    } catch (_) {
      // Unsupported storage must not crash the offline demo or widget tests.
      return null;
    }
  }
  String get _orderKey {
    final user = widget.storageScope;
    return user == null ? 'pd_offline_demo_order_v1' : 'pd_local_order_v1.$user';
  }
  Future<void> _saveQueue = Future<void>.value();
  String? _lastSavedSnapshot;

  Future<void> _restoreOrder() async {
    try {
      if (widget.ordersApi != null) return;
      final saved = await _orderPrefs?.getString(_orderKey);
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
        await _orderPrefs?.setString(_orderKey, snapshot);
      } catch (_) {
        // Demo stays functional even without device storage.
      }
    });
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _orderPrefs = _openOrderPrefs();
    _trip.addListener(_onPilotShiftChanged);
    unawaited(_restoreOrder());
  }

  Future<void> _requestPilotLocation() async {
    if (!widget.enableMapTiles) return;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        _schedulePilotGpsRetry();
        return;
      }
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

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appInForeground = state == AppLifecycleState.resumed;
    if (_appInForeground && _trip.pilotOnline) {
      _onPilotShiftChanged();
    }
  }

  void _schedulePilotGpsRetry() {
    _pilotGpsRetry?.cancel();
    if (!mounted || !_trip.pilotOnline || !widget.enableMapTiles) return;
    _pilotGpsRetry = Timer(const Duration(seconds: 5), () {
      _pilotGpsRetry = null;
      if (mounted && _trip.pilotOnline && _appInForeground) {
        _onPilotShiftChanged();
      }
    });
  }

  void _onPilotShiftChanged() {
    if (!_trip.pilotOnline) {
      _pilotGpsRetry?.cancel();
      _pilotGpsRetry = null;
      _pilotLocationStream?.cancel();
      _pilotLocationStream = null;
      return;
    }
    if (_pilotLocationStream == null && !_startingLocation &&
        _pilotGpsRetry == null && _appInForeground && widget.enableMapTiles) {
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
        locationSettings: !kIsWeb && defaultTargetPlatform == TargetPlatform.android
            ? AndroidSettings(
                accuracy: LocationAccuracy.high,
                distanceFilter: 5,
                intervalDuration: const Duration(seconds: 5),
                foregroundNotificationConfig: const ForegroundNotificationConfig(
                  notificationTitle: 'PRIVATE DRIVE',
                  notificationText: 'Рабочая смена активна',
                  enableWakeLock: true,
                  setOngoing: true,
                ),
              )
            : const LocationSettings(
                accuracy: LocationAccuracy.high, distanceFilter: 5,
              ),
      ).listen((position) {
        if (mounted && _trip.pilotOnline) {
          _trip.updatePilotLocation(position.latitude, position.longitude);
        }
      }, onError: (Object error) {
        // Recover from temporary Android location-stream interruptions.
        _pilotLocationStream?.cancel();
        _pilotLocationStream = null;
        debugPrint('PD_PILOT_GPS_STREAM_INTERRUPTED: ${error.runtimeType}');
        _schedulePilotGpsRetry();
      }, onDone: () {
        _pilotLocationStream = null;
        _schedulePilotGpsRetry();
      });
    } catch (_) {
      // Never invent a GPS fix when Android location is unavailable.
      _schedulePilotGpsRetry();
    } finally {
      _startingLocation = false;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pilotGpsRetry?.cancel();
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
    if (widget.pilotOnly) {
      return PilotCabin(
        enableMapTiles: widget.enableMapTiles,
        tripStore: _trip,
        onSignOut: widget.onSignOut,
        onBackToCabinets: widget.onBackToCabinets,
      );
    }
    if (widget.adminOnly) {
      return Scaffold(
        appBar: AppBar(
          title: const Text('PRIVATE DRIVE · Диспетчер'),
          leading: widget.onBackToCabinets == null
              ? null
              : BackButton(onPressed: widget.onBackToCabinets),
          actions: [
            if (PdIdentityScope.maybeOf(context) != null)
              IconButton(
                key: const Key('dispatcher-photo-review'),
                tooltip: 'Фотоконтроль пилотов',
                icon: const Icon(Icons.verified_user_outlined),
                onPressed: () => Navigator.push(context, MaterialPageRoute<void>(
                  builder: (_) => PdIdentityReviewPage(api: PdIdentityScope.maybeOf(context)!),
                )),
              ),
            if (widget.onSignOut != null)
              IconButton(
                key: const Key('admin-sign-out'),
                tooltip: 'Выйти',
                icon: const Icon(Icons.logout),
                onPressed: widget.onSignOut,
              ),
          ],
        ),
        body: DemoDispatcherCabinet(
          tripStore: _trip,
          enableMapTiles: widget.enableMapTiles,
        ),
      );
    }
    if (widget.passengerOnly) {
      return PdPassengerLanguageScope(
        child: PassengerRideEntry(
          enableMapTiles: widget.enableMapTiles,
          tripStore: _trip,
          onSignOut: widget.onSignOut,
          onBackToCabinets: widget.onBackToCabinets,
          ordersApi: widget.ordersApi,
        ),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text('PRIVATE DRIVE · ${pdTr(context, 'Демоверсия', 'Demonstracija', 'Demo')}')),
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
                    Text(pdLabel(context, 'Выбери тестовый интерфейс'),
                        style: const TextStyle(fontSize: 22)),
                    const SizedBox(height: 12),
                    Text(pdLabel(context,
                      'Тестовые заявки сохраняются на этом устройстве. '
                      'Нет реальных заказов, платежей и сервера.'),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 18),
                    AnimatedBuilder(
                      animation: _trip,
                      builder: (context, _) => Column(
                        children: [
                          Text(pdLabel(context, _trip.statusLabel),
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
                        MaterialPageRoute(builder: (_) => PdPassengerLanguageScope(
                          child: PassengerRideEntry(
                            enableMapTiles: widget.enableMapTiles,
                            tripStore: _trip,
                          ),
                        ))),
                      icon: const Icon(Icons.person_outline),
                      label: Text(pdLabel(context, 'Пассажир')),
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
                      label: Text(pdLabel(context, 'Кабина пилота')),
                    ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      key: const Key('open-dispatcher-preview'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => DemoDispatcherCabinet(
                          tripStore: _trip,
                          enableMapTiles: widget.enableMapTiles,
                        ))),
                      icon: const Icon(Icons.support_agent),
                      label: Text(pdLabel(context, 'Кабинет диспетчера · демо')),
                    ),
                    const SizedBox(height: 12),
                    if (_trip.trip != null) ...[
                      OutlinedButton.icon(
                        key: const Key('open-my-orders'),
                        onPressed: () => Navigator.push(context,
                          MaterialPageRoute(builder: (_) =>
                            PdPassengerLanguageScope(
                              child: PassengerOrdersDemo(tripStore: _trip)))),
                        icon: const Icon(Icons.receipt_long_outlined),
                        label: Text(pdLabel(context, 'Мои заказы · управление')),
                      ),
                      const SizedBox(height: 12),
                    ],
                    OutlinedButton.icon(
                      key: const Key('open-remote-sync-demo'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const RemoteSyncDemo())),
                      icon: const Icon(Icons.sync_alt),
                      label: Text(pdLabel(context, 'Тестовая связь между устройствами')),
                    ),
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      key: const Key('open-company-info'),
                      onPressed: () => Navigator.push(context,
                        MaterialPageRoute(
                          builder: (_) => const CompanyInfoPage())),
                      icon: const Icon(Icons.info_outline),
                      label: Text(pdLabel(context, 'О компании · Контакты · Соглашение')),
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
    this.onIncomingMessageVoice,
    this.showAssignedOffer = true,
    this.testRoadPoints,
  }) : deviceLocationOnly = false,
       deviceTileProviderForTest = null;

  /// Existing map surface, but explicitly without trip, chat, payment, or
  /// server-sharing controls. Only local device positioning may be enabled.
  const PilotDemo.ownDevice({
    super.key,
    this.enableMapTiles = true,
    this.mapController,
    this.loadMapTiles = true,
    this.deviceTileProviderForTest,
  }) : deviceLocationOnly = true,
       positions = null,
       tripStore = null,
       onIncomingSound = null,
       onIncomingMessageVoice = null,
       showAssignedOffer = false,
       testRoadPoints = null;

  final bool deviceLocationOnly;
  /// Optional recording boundary for widget tests of the ordinary online map.
  /// It is never used for the private GPS surface.
  final TileProvider Function()? deviceTileProviderForTest;

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
  /// Test hook: only new incoming passenger messages trigger this callback.
  final VoidCallback? onIncomingMessageVoice;
  /// The premium cockpit renders this offer in the root overlay instead.
  final bool showAssignedOffer;
  /// Synthetic route fixture for widget tests only; never used by app UI.
  final List<LatLng>? testRoadPoints;

  @override
  State<PilotDemo> createState() => _PilotDemoState();
}

class _PilotDemoState extends State<PilotDemo>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late final MapController _map = widget.mapController ?? MapController();
  StreamSubscription<Position>? _gps;
  StreamSubscription<LatLng>? _synthetic;
  bool _deviceLocationForeground = true;
  bool _deviceLocationStarting = false;
  bool _devicePrivateSurface = false;
  int _deviceLocationGeneration = 0;
  LatLng? _position;
  LatLng? _displayPosition;
  double _headingDegrees = 0;
  bool _nightMap = false;
  int _pilotTileErrors = 0;
  bool _pilotTilesFailed = false;
  int _pilotTileRetry = 0;
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
    try {
      final uri = Uri.https('router.project-osrm.org',
        '/route/v1/driving/${from.longitude},${from.latitude};'
        '${to.longitude},${to.latitude}',
        {'overview': 'full', 'geometries': 'geojson'});
      final decoded = await const PdHttpApi().getJson(uri);
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
    }
  }

  final PilotOfferTone _demoOfferTone = PilotOfferTone();
  bool _incomingOffer = false;
  bool _nextAccepted = false;

  bool get _isUnderway => widget.tripStore?.status == DemoTripStatus.underway;

  void _simulateNewOffer() {
    if (!_isUnderway || _incomingOffer || _nextAccepted) return;
    setState(() => _incomingOffer = true);
    if (widget.onIncomingSound != null) {
      widget.onIncomingSound!();
    } else {
      if (PilotSoundSettings.instance.enabled) {
        unawaited(_demoOfferTone.play(melody: PilotSoundSettings.instance.melody));
      }
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
        tripStore: widget.tripStore!,
        messages: [
          ...widget.tripStore!.pilotChatMessages,
          ...widget.tripStore!.passengerChatMessages.map(
            (message) => 'Пассажир: $message'),
        ],
        onSend: (text) => _hasAssignedPassenger &&
            widget.tripStore!.addPilotChatMessage(text),
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
        title: Text(pdLabel(context, 'Позвонить пассажиру')),
        content: const Text(
          'Это локальная демоверсия. Подтверждённого номера пассажира нет. '
          'Реальный звонок не выполняется.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(pdLabel(context, 'Понятно')),
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
  bool _tripPanelCollapsed = false;
  int _pilotPassengerStars = 0;
  String _gpsMessage = 'GPS выключен';
  int stage = 0;
  bool paused = false;
  Timer? _waitingTicker;
  Timer? _pickupWaitingTicker;
  DateTime? _waitingStartedAt;
  Duration _waitingElapsed = Duration.zero;
  DemoTrip? _waitingTripId;
  int _seenPassengerMessageCount = 0;

  Duration get _waitingTotal => _waitingElapsed +
      (_waitingStartedAt == null ? Duration.zero :
      DateTime.now().difference(_waitingStartedAt!));

  String get _waitingClock {
    final seconds = _waitingTotal.inSeconds;
    return '${(seconds ~/ 3600).toString().padLeft(2, '0')}:'
        '${((seconds ~/ 60) % 60).toString().padLeft(2, '0')}:'
        '${(seconds % 60).toString().padLeft(2, '0')}';
  }

  void _togglePaidWait() {
    final currentlyPaused = widget.tripStore?.paused ?? paused;
    if (!currentlyPaused) {
      _waitingStartedAt = DateTime.now();
      _waitingTicker ??= Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    } else {
      if (_waitingStartedAt != null) {
        _waitingElapsed += DateTime.now().difference(_waitingStartedAt!);
      }
      _waitingStartedAt = null;
      _waitingTicker?.cancel();
      _waitingTicker = null;
    }
    if (widget.tripStore != null) {
      widget.tripStore!.togglePause();
    } else {
      setState(() => paused = !paused);
    }
  }
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
    if (widget.deviceLocationOnly) {
      final lifecycle = WidgetsBinding.instance.lifecycleState;
      _deviceLocationForeground =
          lifecycle == null || lifecycle == AppLifecycleState.resumed;
      WidgetsBinding.instance.addObserver(this);
      return;
    }
    _seenPassengerMessageCount =
        widget.tripStore?.passengerChatMessages.length ?? 0;
    widget.tripStore?.addListener(_onTripChanged);
    _syncPickupWaitingTicker();
    if (widget.tripStore?.pilotOnline == true) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _onTripChanged();
      });
    }
  }

  void _syncPickupWaitingTicker() {
    final waiting = widget.tripStore?.isWaitingAtPickup == true;
    if (waiting && _pickupWaitingTicker == null) {
      _pickupWaitingTicker = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    } else if (!waiting) {
      _pickupWaitingTicker?.cancel();
      _pickupWaitingTicker = null;
    }
  }

  String get _pickupWaitingText {
    final store = widget.tripStore!;
    final elapsed = store.pickupWaitingElapsed();
    final seconds = elapsed.inSeconds;
    final clock = '${(seconds ~/ 60).toString().padLeft(2, '0')}:'
        '${(seconds % 60).toString().padLeft(2, '0')}';
    final freeLeft = DemoTripStore.freePickupWaiting - elapsed;
    if (freeLeft > Duration.zero) {
      final left = (freeLeft.inMilliseconds + 999) ~/ 1000;
      return 'Ожидание $clock · бесплатно ещё '
          '${(left ~/ 60).toString().padLeft(2, '0')}:'
          '${(left % 60).toString().padLeft(2, '0')}';
    }
    return 'Платное ожидание $clock · +${store.pickupWaitingFeeLabel()} '
        '(0,30 €/мин)';
  }

  void _onTripChanged() {
    if (!mounted) return;
    _syncPickupWaitingTicker();
    final store = widget.tripStore;
    final count = store?.passengerChatMessages.length ?? 0;
    if (count > _seenPassengerMessageCount) {
      if (widget.onIncomingMessageVoice != null) {
        widget.onIncomingMessageVoice!();
      } else {
        unawaited(PdMessageVoice.announce('пассажира'));
      }
    }
    _seenPassengerMessageCount = count;
    final tripId = store?.trip;
    if (tripId != _waitingTripId) {
      _waitingTripId = tripId;
      _waitingElapsed = Duration.zero;
      _waitingStartedAt = null;
      _waitingTicker?.cancel();
      _waitingTicker = null;
    }
    if (store?.status == DemoTripStatus.finished && _waitingStartedAt != null) {
      _waitingElapsed += DateTime.now().difference(_waitingStartedAt!);
      _waitingStartedAt = null;
      _waitingTicker?.cancel();
      _waitingTicker = null;
    }
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
    // GPS from the attached assignment cabinet must not reach a network map
    // camera, its center button, or the legacy address routing methods.
    if (widget.deviceLocationOnly && !_devicePrivateSurface) return;
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
      _gpsMessage = widget.deviceLocationOnly
          ? 'Моя позиция · не передаётся диспетчеру'
          : 'GPS активен · только на устройстве';
    });
    if (widget.deviceLocationOnly) return;
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

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!widget.deviceLocationOnly) return;
    _deviceLocationForeground = state == AppLifecycleState.resumed;
    if (!_deviceLocationForeground && (_gpsEnabled || _deviceLocationStarting)) {
      final permissionRequestInterrupted = _deviceLocationStarting;
      _stopGps();
      if (permissionRequestInterrupted) {
        setState(() => _gpsMessage = 'Нажми «Показать мою позицию» снова');
      }
    }
  }

  bool _activeDeviceLocation(int generation) =>
      mounted && _deviceLocationForeground &&
      generation == _deviceLocationGeneration;

  Future<void> _enableDeviceLocation() async {
    if (!_deviceLocationForeground || _deviceLocationStarting || _gpsEnabled ||
        !widget.enableMapTiles) {
      return;
    }
    final generation = ++_deviceLocationGeneration;
    setState(() {
      _deviceLocationStarting = true;
      _devicePrivateSurface = true;
      _gpsMessage = 'Проверяем доступ к GPS устройства…';
    });

    void streamEnded([Object? error]) {
      if (!_activeDeviceLocation(generation)) return;
      _stopGps();
      setState(() => _gpsMessage = 'GPS устройства недоступен');
    }

    try {
      // Unmount the TileLayer before requesting permission or any position.
      // The GPS callback is independently forbidden from moving its camera.
      await WidgetsBinding.instance.endOfFrame;
      if (!_activeDeviceLocation(generation)) return;
      final servicesOn = await Geolocator.isLocationServiceEnabled();
      if (!_activeDeviceLocation(generation)) return;
      if (!servicesOn) {
        setState(() => _gpsMessage = 'Включи геолокацию устройства');
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (!_activeDeviceLocation(generation)) return;
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (!_activeDeviceLocation(generation)) return;
      if (permission != LocationPermission.whileInUse &&
          permission != LocationPermission.always) {
        setState(() => _gpsMessage = 'Доступ к GPS не предоставлен');
        return;
      }
      setState(() {
        _gpsEnabled = true;
        _gpsMessage = 'Ожидание координат GPS…';
      });
      _gps = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 5,
        ),
      ).listen((position) {
        if (!_activeDeviceLocation(generation) || position.isMocked) return;
        _onPosition(
          LatLng(position.latitude, position.longitude),
          sensorHeading: position.heading,
          speed: position.speed,
          publishToStore: false,
        );
      }, onError: streamEnded, onDone: streamEnded);
    } catch (_) {
      streamEnded();
    } finally {
      if (_activeDeviceLocation(generation)) {
        setState(() {
          _deviceLocationStarting = false;
          if (!_gpsEnabled) _devicePrivateSurface = false;
        });
      }
    }
  }

  Future<void> _enableGps() async {
    if (widget.deviceLocationOnly) {
      await _enableDeviceLocation();
      return;
    }
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
    if (widget.deviceLocationOnly) {
      _deviceLocationGeneration++;
      _deviceLocationStarting = false;
    }
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
      _devicePrivateSurface = false;
      _gpsMessage = 'GPS выключен';
      _position = null;
    });
  }

  void advance() {
    if (widget.deviceLocationOnly) return;
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
    if (widget.deviceLocationOnly) {
      _deviceLocationGeneration++;
      WidgetsBinding.instance.removeObserver(this);
    }
    _waitingTicker?.cancel();
    _pickupWaitingTicker?.cancel();
    widget.tripStore?.removeListener(_onTripChanged);
    _gps?.cancel();
    _synthetic?.cancel();
    _demoOfferTone.dispose();
    _cameraAnimation.dispose();
    if (widget.mapController == null) _map.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scaffold = Scaffold(
      drawer: widget.deviceLocationOnly ? null : Drawer(
        key: const Key('pilot-navigation-drawer'),
        child: SafeArea(child: ListView(children: [
          const DrawerHeader(child: Center(child: Text('PRIVATE DRIVE · Пилот',
            style: TextStyle(fontSize: 20)))),
          ListTile(
            key: const Key('pilot-drawer-map'),
            leading: const Icon(Icons.map_outlined),
            title: Text(pdLabel(context, 'Карта и текущая поездка')),
            onTap: () => Navigator.pop(context),
          ),
          ListTile(
            key: const Key('pilot-drawer-trip-status'),
            leading: const Icon(Icons.route_outlined),
            title: Text(pdLabel(context, 'Статус поездки')),
            subtitle: Text(pdLabel(context, _tripLabel)),
            onTap: () => Navigator.pop(context),
          ),
          ListTile(
            key: const Key('pilot-drawer-remote-chat'),
            leading: const Icon(Icons.chat_outlined),
            title: const Text('Сообщения между устройствами · тест'),
            onTap: () {
              Navigator.pop(context);
              Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => Scaffold(
                  appBar: AppBar(title: const Text('Тестовый чат пилота')),
                  body: const SafeArea(child: SingleChildScrollView(
                    padding: EdgeInsets.all(16),
                    child: IsolatedTripChat(expectedRole: 'pilot'),
                  )),
                ),
              ));
            },
          ),
          ListTile(
            key: const Key('pilot-drawer-sounds'),
            leading: const Icon(Icons.volume_up_outlined),
            title: Text(pdLabel(context, 'Настройки звуков')),
            subtitle: const Text('Заказы: 3 мелодии или без звука'),
            onTap: () {
              Navigator.pop(context);
              Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => const PilotSoundSettingsPage()));
            },
          ),
          ListTile(
            key: const Key('pilot-drawer-cash-settings'),
            leading: const Icon(Icons.payments_outlined),
            title: const Text('Настройки оплаты'),
            subtitle: const Text('Принимать наличные: включить / выключить'),
            onTap: () {
              Navigator.pop(context);
              Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => PilotPaymentSettingsPage(
                  tripStore: widget.tripStore)));
            },
          ),
          ListTile(
            key: const Key('pilot-drawer-history'),
            leading: const Icon(Icons.history),
            title: Text(pdLabel(context, 'История и заработок')),
            subtitle: const Text('После подключения защищённого API'),
            enabled: false,
          ),
          ListTile(
            key: const Key('pilot-drawer-vehicle'),
            leading: const Icon(Icons.directions_car_outlined),
            title: Text(pdLabel(context, 'Автомобиль и документы')),
            subtitle: const Text('После регистрации пилота'),
            enabled: false,
          ),
          ListTile(
            key: const Key('pilot-drawer-language'),
            leading: const Icon(Icons.language),
            title: Text(pdLabel(context, 'Язык')),
            trailing: const PdLanguageMenu(),
          ),
          ListTile(
            key: const Key('pilot-drawer-support'),
            leading: const Icon(Icons.help_outline),
            title: Text(pdLabel(context, 'Поддержка')),
            onTap: () {
              Navigator.pop(context);
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => const CompanyInfoPage()));
            },
          ),
        ])),
      ),
      body: Stack(
        fit: StackFit.expand,
        children: [
          if (_devicePrivateSurface)
            _PilotDevicePositionGrid(
              position: _position,
              headingDegrees: _headingDegrees,
              night: _nightMap,
            )
          else if (widget.enableMapTiles)
            KeyedSubtree(
              key: ValueKey('pilot-map-retry-$_pilotTileRetry'),
              child: FlutterMap(
              key: const Key('pilot-map-surface'),
              mapController: _map,
              options: MapOptions(
                initialCenter: vilnius,
                initialZoom: 14,
                backgroundColor: _nightMap
                  ? const Color(0xFF101B2B)
                  : const Color(0xFFE0EAF0),
              ),
              children: [
                if (widget.loadMapTiles)
                  ColorFiltered(
                    key: const Key('pilot-map-night-filter'),
                    colorFilter: _nightMap
                        ? const ColorFilter.matrix(<double>[
                            -0.65, 0, 0, 0, 170,
                            0, -0.65, 0, 0, 170,
                            0, 0, -0.65, 0, 170,
                            0, 0, 0, 1, 0,
                          ])
                        : const ColorFilter.matrix(<double>[
                            1, 0, 0, 0, 0,
                            0, 1, 0, 0, 0,
                            0, 0, 1, 0, 0,
                            0, 0, 0, 1, 0,
                          ]),
                    child: TileLayer(
                    key: const Key('pilot-map-tiles'),
                    tileProvider: widget.deviceTileProviderForTest?.call() ??
                        demoTileProvider(),
                    // Raster OSM tiles need no CARTO API key.
                    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                    userAgentPackageName: 'lt.privatedrive.private_drive.demo',
                    maxNativeZoom: 19,
                    errorTileCallback: (tile, error, stackTrace) {
                    if (!widget.deviceLocationOnly) {
                      debugPrint('PD_PILOT_TILE_ERROR: $error');
                    }
                      WidgetsBinding.instance.addPostFrameCallback((_) {
                        if (!mounted || _pilotTilesFailed) return;
                        setState(() {
                          _pilotTileErrors++;
                          if (_pilotTileErrors >= 3) _pilotTilesFailed = true;
                        });
                      });
                    },
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
                        child: const Icon(
                          Icons.local_taxi_rounded,
                          key: Key('pilot-location-marker'),
                          color: Color(0xFFDDC184),
                          size: 44,
                          shadows: [
                            Shadow(color: Colors.black, blurRadius: 9),
                            Shadow(color: Color(0xFF172B3F), blurRadius: 4),
                          ],
                        ),
                      ),
                    ),
                  ]),
                const RichAttributionWidget(
                  attributions: [
                    TextSourceAttribution('© OpenStreetMap contributors'),
                    TextSourceAttribution('© CARTO'),
                  ],
                ),
              ],
            ),
            )
          else
            const RepaintBoundary(
              child: CustomPaint(
                key: Key('pilot-map-surface'),
                painter: DemoMapPainter(),
              ),
            ),
          if (!_devicePrivateSurface && widget.enableMapTiles &&
              widget.loadMapTiles && _pilotTilesFailed)
            Positioned.fill(
              child: ColoredBox(
                color: const Color(0xD9172535),
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.map_outlined, color: Colors.white,
                          size: 38),
                      Text(pdLabel(context, 'Карта пилота не загрузилась'),
                        key: Key('pilot-map-load-error'),
                        style: TextStyle(color: Colors.white)),
                      TextButton.icon(
                        key: const Key('pilot-map-retry'),
                        onPressed: () => setState(() {
                          _pilotTileRetry++;
                          _pilotTileErrors = 0;
                          _pilotTilesFailed = false;
                        }),
                        icon: const Icon(Icons.refresh),
                        label: Text(pdLabel(context, 'Повторить загрузку карты')),
                      ),
                    ],
                  ),
                ),
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
                    tooltip: pdLabel(context, 'Назад'),
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.arrow_back),
                  ),
                ),
                if (!widget.deviceLocationOnly)
                Positioned(
                  top: 64,
                  left: 12,
                  child: Builder(builder: (menuContext) => IconButton.filledTonal(
                    key: const Key('pilot-open-drawer'),
                    tooltip: pdLabel(context, 'Меню пилота'),
                    onPressed: () => Scaffold.of(menuContext).openDrawer(),
                    icon: const Icon(Icons.menu),
                  )),
                ),
                if (!widget.deviceLocationOnly)
                Positioned(
                  top: 120,
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
                  top: widget.deviceLocationOnly ? 64 : 176,
                  left: 12,
                  child: Material(
                    color: const Color(0xF0172535),
                    borderRadius: BorderRadius.circular(14),
                    child: IconButton(
                      key: const Key('pilot-map-day-night'),
                      tooltip: pdLabel(context, _nightMap ? 'Дневная карта' : 'Ночная карта'),
                      icon: Icon(_nightMap ? Icons.wb_sunny_outlined
                        : Icons.dark_mode_outlined,
                        color: const Color(0xFFDDC184), size: 22),
                      onPressed: () => setState(() {
                        _nightMap = !_nightMap;
                        _pilotTilesFailed = false;
                        _pilotTileErrors = 0;
                      }),
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
                        color: Color(0xFFB6FF36),
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
                          tooltip: widget.deviceLocationOnly
                              ? 'Показать мою позицию'
                              : pdLabel(context, 'Включить GPS'),
                          onPressed: _deviceLocationStarting ? null : _enableGps,
                          child: const Icon(Icons.my_location),
                        )
                      else
                        FloatingActionButton.small(
                          key: const Key('pilot-disable-gps'),
                          heroTag: 'pilot-stop-gps',
                          tooltip: pdLabel(context, 'Выключить GPS'),
                          onPressed: _stopGps,
                          child: const Icon(Icons.location_off),
                        ),
                      if (!widget.deviceLocationOnly && _gpsEnabled &&
                          _position != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: FloatingActionButton.small(
                            key: const Key('pilot-center-map'),
                            heroTag: 'pilot-center',
                            tooltip: pdLabel(context, 'Центрировать карту'),
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
                if (widget.deviceLocationOnly)
                  const Align(
                    alignment: Alignment.bottomCenter,
                    child: Padding(
                      padding: EdgeInsets.all(12),
                      child: Chip(label: Text('Позиция диспетчеру не передаётся')),
                    ),
                  )
                else
                  Align(
                  alignment: Alignment.bottomCenter,
                  child: GestureDetector(
                    onVerticalDragEnd: (details) {
                      if (details.primaryVelocity == null) return;
                      if (details.primaryVelocity! > 180 && !_tripPanelCollapsed) {
                        setState(() => _tripPanelCollapsed = true);
                      } else if (details.primaryVelocity! < -180 && _tripPanelCollapsed) {
                        setState(() => _tripPanelCollapsed = false);
                      }
                    },
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
                            InkWell(
                              key: const Key('pilot-trip-panel-toggle'),
                              onTap: () => setState(() =>
                                _tripPanelCollapsed = !_tripPanelCollapsed),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(vertical: 3),
                                child: Row(children: [
                                  const SizedBox(width: 12),
                                  Expanded(child: Text(pdLabel(context, _tripLabel),
                                    key: const Key('pilot-trip-state'),
                                    textAlign: TextAlign.center)),
                                  Icon(_tripPanelCollapsed
                                    ? Icons.keyboard_arrow_up
                                    : Icons.keyboard_arrow_down),
                                ]),
                              ),
                            ),
                            if (!_tripPanelCollapsed) ...[
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
                                    Text(pdLabel(context, 'Новый назначенный заказ · демо'),
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
                                          child: Text(pdLabel(context, 'Принять')),
                                        ),
                                      ),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: OutlinedButton(
                                          key: const Key('pilot-decline-assigned'),
                                          onPressed: widget.tripStore!.declineAssignedPilot,
                                          child: Text(pdLabel(context, 'Отклонить')),
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
                                label: Text(pdLabel(context, 'Сымитировать новый заказ')),
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
                                            child: Text(pdLabel(context, 'Принять следующий')),
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
                                            child: Text(pdLabel(context, 'Пропустить')),
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
                                      label: Text(pdLabel(context, 'Написать')),
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: OutlinedButton.icon(
                                      key: const Key('pilot-passenger-call'),
                                      onPressed: _showCallDemo,
                                      icon: const Icon(Icons.call_outlined),
                                      label: Text(pdLabel(context, 'Позвонить')),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                            ],

                            if (widget.tripStore?.status ==
                                DemoTripStatus.approaching &&
                                widget.tripStore?.pilotAccepted == true &&
                                widget.tripStore?.arrivalAt == null)
                              FilledButton.icon(
                                key: const Key('pilot-arrived-at-pickup'),
                                onPressed: () => widget.tripStore!.markArrived(),
                                icon: const Icon(Icons.pin_drop_outlined),
                                label: const Text('Прибыл · 3 минуты бесплатно'),
                              ),
                            if (widget.tripStore?.arrivalAt != null)
                              Text(
                                _pickupWaitingText,
                                key: const Key('pilot-pickup-waiting-meter'),
                                style: const TextStyle(
                                  color: Color(0xFFDDC184),
                                  fontWeight: FontWeight.bold),
                              ),
                            const SizedBox(height: 4),
                            if ((widget.tripStore?.paused ?? paused) ||
                                _waitingElapsed > Duration.zero)
                              Text('Остановка · $_waitingClock · без начисления за посадку',
                                key: const Key('pilot-paid-wait-timer'),
                                style: const TextStyle(
                                  color: Color(0xFFDDC184),
                                  fontWeight: FontWeight.bold)),
                            Row(
                              children: [
                                Expanded(
                                  child: PdSlideToConfirm(
                                    key: const Key('pilot-next-trip'),
                                    thumbKey: const Key('pilot-next-trip-handle'),
                                    label: pdLabel(context, _actionText),
                                    enabled: _canAdvance,
                                    color: const Color(0xFF27764E),
                                    onConfirmed: advance,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                OutlinedButton(
                                  key: const Key('pilot-pause-trip'),
                                  onPressed: !_canPause ? null : _togglePaidWait,
                                  child: Text((widget.tripStore?.paused ?? paused)
                                      ? 'Продолжить' : 'Остановка'),
                                ),
                              ],
                            ),
                            if (widget.tripStore?.status == DemoTripStatus.finished)
                              Card(
                                key: const Key('pilot-rate-passenger-panel'),
                                child: Padding(
                                  padding: const EdgeInsets.all(8),
                                  child: Column(children: [
                                    const Text('Оцени пассажира',
                                      style: TextStyle(fontWeight: FontWeight.bold)),
                                    if (widget.tripStore!.passengerRatingByPilot != null)
                                      Text('Оценка сохранена: ${widget.tripStore!.passengerRatingByPilot}/5',
                                        key: const Key('pilot-passenger-rating-saved'))
                                    else ...[
                                      Row(
                                        mainAxisAlignment: MainAxisAlignment.center,
                                        children: [
                                          for (var stars = 1; stars <= 5; stars++)
                                            IconButton(
                                              key: Key('pilot-rate-passenger-$stars'),
                                              onPressed: () => setState(() =>
                                                _pilotPassengerStars = stars),
                                              icon: Icon(
                                                _pilotPassengerStars >= stars
                                                  ? Icons.star : Icons.star_border,
                                                color: const Color(0xFFDDC184)),
                                            ),
                                        ],
                                      ),
                                      FilledButton(
                                        key: const Key('pilot-submit-passenger-rating'),
                                        onPressed: _pilotPassengerStars == 0 ? null
                                          : () {
                                              if (widget.tripStore!.ratePassengerByPilot(
                                                  _pilotPassengerStars)) {
                                                setState(() {});
                                              }
                                            },
                                        child: const Text('Сохранить оценку · демо'),
                                      ),
                                    ],
                                  ]),
                                ),
                              ),
                            ], // expanded trip panel contents
                          ],
                        ),
                      ),
                    ),
                  ),
                  ), // swipeable trip panel
                ),
              ],
            ),
          ),
        ],
      ),
    );
    if (!widget.deviceLocationOnly) return scaffold;
    return PopScope<void>(
      onPopInvokedWithResult: (didPop, _) {
        if (didPop && mounted && (_gpsEnabled || _deviceLocationStarting)) {
          _stopGps();
        }
      },
      child: scaffold,
    );
  }
}

/// An explicitly offline position display. This intentionally has no maps SDK,
/// tile layer, map controller, address routing, or synthetic place markers.
class _PilotDevicePositionGrid extends StatelessWidget {
  const _PilotDevicePositionGrid({
    required this.position,
    required this.headingDegrees,
    required this.night,
  });

  final LatLng? position;
  final double headingDegrees;
  final bool night;

  @override
  Widget build(BuildContext context) {
    final fix = position;
    return ColoredBox(
      key: const Key('pilot-device-position-grid'),
      color: night ? const Color(0xFF101B2B) : const Color(0xFFE0EAF0),
      child: CustomPaint(
        painter: _PilotDeviceGridPainter(night: night),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (fix != null) ...[
                Transform.rotate(
                  angle: headingDegrees * math.pi / 180,
                  child: const Icon(
                    Icons.local_taxi_rounded,
                    key: Key('pilot-location-marker'),
                    color: Color(0xFFB68114),
                    size: 44,
                  ),
                ),
                Text(
                  '${fix.latitude.toStringAsFixed(5)}, '
                  '${fix.longitude.toStringAsFixed(5)}',
                  style: TextStyle(color: night ? Colors.white : Colors.black),
                ),
              ],
              Text(
                'Локальная сетка без интернет-карты',
                style: TextStyle(color: night ? Colors.white : Colors.black),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PilotDeviceGridPainter extends CustomPainter {
  const _PilotDeviceGridPainter({required this.night});

  final bool night;

  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()
      ..color = night ? const Color(0xFF263A50) : const Color(0xFFB6C9D3);
    const spacing = 32.0;
    for (double x = size.width / 2 % spacing; x < size.width; x += spacing) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (double y = size.height / 2 % spacing; y < size.height; y += spacing) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
  }

  @override
  bool shouldRepaint(_PilotDeviceGridPainter oldDelegate) =>
      night != oldDelegate.night;
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
