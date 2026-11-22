import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'permissions_onboarding.dart';
import 'message_voice.dart';
import 'app_language.dart';
import 'demo_trip_store.dart';
import 'taxi_fare.dart';
import 'pd_pickup_fee.dart';
import 'demo_rating_panel.dart';
import 'company_info.dart';
import 'passenger_orders_demo.dart';
import 'passenger_extra_services.dart';
import 'pd_pilot_assignment_waiting.dart';
import 'passenger_preferences_storage.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'demo_map_tile_provider.dart';
import 'pd_mapbox_qa_config.dart';
import 'pd_http_api.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:url_launcher/url_launcher.dart';

/// Passenger preview: all trip, date, service and payment state stays in memory.
/// The payment information link opens the website in an external browser.
/// This screen does not collect payments or submit bookings.
class PassengerDemo extends StatefulWidget {
  const PassengerDemo({super.key, this.enableMapTiles = true, this.tripStore,
      this.preferencesStorage, this.initialRideType = 'Трансфер',
      this.initialAdvanceBooking = false,
      this.initialAdvanceDate, this.initialAdvanceTime,
      this.mapConnectivityCheck, this.currentPositionLoader, this.passengerMapController,
      this.onIncomingMessageVoice});

  final bool enableMapTiles;
  final String initialRideType;
  final bool initialAdvanceBooking;
  final DateTime? initialAdvanceDate;
  final TimeOfDay? initialAdvanceTime;
  /// Test injection: null uses a real HTTPS tile request on Android.
  final Future<String?> Function()? mapConnectivityCheck;
  final DemoTripStore? tripStore;
  final Future<LatLng> Function()? currentPositionLoader;
  final MapController? passengerMapController;
  /// A test hook; production reads a short TTS phrase for a new pilot message.
  final VoidCallback? onIncomingMessageVoice;
  final PassengerPreferencesStorage? preferencesStorage;

  @override
  State<PassengerDemo> createState() => _PassengerDemoState();
}

class _PassengerDemoState extends State<PassengerDemo> {
  final _from = TextEditingController();
  final _to = TextEditingController();
  final _tripWishes = TextEditingController();
  final _favoriteTracks = List.generate(3, (_) => TextEditingController());
  String _radioStation = 'Без радио';
  double? _cabinTemperature;
  DateTime? _date;
  TimeOfDay? _time;
  String _route = '';
  Future<void> _openPayseraPaymentInfo() async {
    try {
      final opened = await launchUrl(
        Uri.https('privatedrive.lt', '/payment/paysera'),
        mode: LaunchMode.externalApplication,
      );
      if (opened) return;
    } on Exception {
      // Show the same message when the platform cannot open the browser.
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(pdTr(
      context,
      'Не удалось открыть страницу Paysera.',
      'Nepavyko atidaryti „Paysera“ puslapio.',
      'Could not open the Paysera page.',
    ))));
  }

  String _payment = 'Карта';
  late String _rideType;
  bool _roundTrip = false;
  bool _taxiOutsideCity = false;
  bool _taxiAdvanceBooking = false;
  int? _roadDistanceMetres;
  bool _meetSign = false;
  bool _pets = false;
  bool _soberDriver = false;
  bool _music = false;
  bool _flowers = false;
  bool _coffee = false;
  bool _nightMap = false;
  String _menuSection = 'booking';
  bool _followPilot = true;
  LatLng? _lastPilotCameraFix;
  final DraggableScrollableController _passengerSheetController = DraggableScrollableController();
  late final MapController _passengerMapController = widget.passengerMapController ?? MapController();
  bool _findingPassenger = false;
  LatLng? _passengerLocation;
  LatLng? _pickedPickup;
  String? _locationMessage;
  bool _mapTilesFailed = false;
  bool _useBackupTiles = false;
  String? _lastTileError;
  String? _mapNetworkError;
  bool _checkingMapNetwork = false;
  int _mapTileErrors = 0;
  int _tileRetry = 0;
  bool _water = false;
  bool _quietRide = false;
  bool _luggageHelp = false;
  List<LatLng> _roadPoints = const [];
  int? _pickupEtaMinutes;
  int? _pickupRoadMetres;
  int _pickupEtaGeneration = 0;
  String? _pickupEtaRouteKey;
  DateTime? _pickupEtaRequestedAt;

  /// Uses actual pilot GPS and a resolved pickup address; never assumes
  /// average speed or invents an arrival time for a city-centre placeholder.
  Future<void> _updatePickupEta() async {
    final store = widget.tripStore;
    final trip = store?.trip;
    final lastFix = store?.pilotLastSeen;
    final eligible = widget.enableMapTiles && trip != null &&
        (store?.status == DemoTripStatus.assigned && store?.pilotAccepted == true ||
         store?.status == DemoTripStatus.approaching) &&
        store?.pilotOnline == true && store?.pilotLatitude != null &&
        store?.pilotLongitude != null && lastFix != null &&
        !lastFix.isAfter(DateTime.now()) &&
        DateTime.now().difference(lastFix) < const Duration(minutes: 2);
    final pickup = trip == null ? null :
        (_pickedPickup ?? _resolve(trip.from));
    if (!eligible || pickup == null) {
      _pickupEtaGeneration++;
      _pickupEtaRouteKey = null;
      _pickupEtaMinutes = null;
      _pickupRoadMetres = null;
      return;
    }
    final lat = store!.pilotLatitude!;
    final lng = store.pilotLongitude!;
    final key = '${lat.toStringAsFixed(4)},${lng.toStringAsFixed(4)}'
        ':${pickup.latitude.toStringAsFixed(5)},${pickup.longitude.toStringAsFixed(5)}';
    if (_pickupEtaRouteKey == key &&
        _pickupEtaRequestedAt != null &&
        DateTime.now().difference(_pickupEtaRequestedAt!) <
            const Duration(seconds: 30)) return;
    _pickupEtaRouteKey = key;
    _pickupEtaRequestedAt = DateTime.now();
    _pickupEtaMinutes = null;
    _pickupRoadMetres = null;
    final request = ++_pickupEtaGeneration;
    try {
      final uri = Uri.https('router.project-osrm.org',
        '/route/v1/driving/$lng,$lat;${pickup.longitude},${pickup.latitude}',
        {'overview': 'false'});
      final json = await const PdHttpApi().getJson(
        uri, timeout: const Duration(seconds: 8));
      final routes = json['routes'] as List<dynamic>?;
      if (routes == null || routes.isEmpty) throw const FormatException('No route');
      final roadRoute = routes.first as Map<String, dynamic>;
      final duration = roadRoute['duration'];
      final distance = roadRoute['distance'];
      if (duration is! num || !duration.isFinite || duration < 0 ||
          distance is! num || !distance.isFinite ||
          distance < 0 || distance > 2000000) {
        throw const FormatException('Invalid route distance or duration');
      }
      if (!mounted || request != _pickupEtaGeneration) return;
      // OSRM driving duration excludes live traffic and is only indicative.
      setState(() {
        _pickupEtaMinutes =
            (duration.toDouble() / 60).ceil().clamp(1, 1440);
        _pickupRoadMetres = distance.round();
      });
    } catch (_) {
      if (!mounted || request != _pickupEtaGeneration) return;
      setState(() {
        _pickupEtaMinutes = null;
        _pickupRoadMetres = null;
      });
    }
  }

  bool _routeLoading = false;
  String _routeInfo = '';
  int _routeRequest = 0;
  Timer? _addressTimer;
  Timer? _gpsFreshnessTimer;
  int _addressGeneration = 0;
  String? _editingAddress;
  List<String> _addressSuggestions = const [];
  String? _addressSearchError;
  final Map<String, LatLng> _resolvedAddresses = {};
  late final PassengerPreferencesStorage _preferencesStorage =
      widget.preferencesStorage ?? DevicePassengerPreferencesStorage();
  bool _preferencesReady = false;
  bool _restoringPreferences = false;
  String? _lastPreferencesSnapshot;
  String? _queuedPreferencesSnapshot;
  Future<void> _pendingPreferencesWrite = Future<void>.value();

  Map<String, dynamic> _preferencesSnapshot() => {
    'version': 1,
    'radio': _radioStation,
    'tracks': _favoriteTracks.map((c) => c.text).toList(),
    'temperature': _cabinTemperature,
    'meetSign': _meetSign, 'pets': _pets, 'soberDriver': _soberDriver,
    'music': _music, 'flowers': _flowers, 'coffee': _coffee,
    'water': _water, 'quietRide': _quietRide, 'luggageHelp': _luggageHelp,
    'wishes': _tripWishes.text,
  };

  void _savePreferences() {
    if (!_preferencesReady || _restoringPreferences) return;
    final snapshot = jsonEncode(_preferencesSnapshot());
    if (snapshot == _lastPreferencesSnapshot ||
        snapshot == _queuedPreferencesSnapshot) return;
    _queuedPreferencesSnapshot = snapshot;
    _pendingPreferencesWrite = _pendingPreferencesWrite.then((_) async {
      try {
        await _preferencesStorage.write(snapshot);
        _lastPreferencesSnapshot = snapshot;
      } catch (_) {
        // Keep the previous confirmed snapshot so a later edit can retry.
      } finally {
        if (_queuedPreferencesSnapshot == snapshot) {
          _queuedPreferencesSnapshot = null;
        }
      }
    });
  }

  Future<void> _restorePreferences() async {
    String? saved;
    try {
      saved = await _preferencesStorage.read();
    } catch (_) {
      // Local storage may be unavailable in a test environment.
    }
    if (!mounted) return;
    _restoringPreferences = true;
    if (saved != null) {
      try {
        final data = jsonDecode(saved);
        if (data is Map<String, dynamic> && data['version'] == 1) {
          final radio = data['radio'];
          final tracks = data['tracks'];
          final temperature = data['temperature'];
          final wishes = data['wishes'];
          setState(() {
            _radioStation = radio is String && _vilniusRadio.contains(radio)
                ? radio : 'Без радио';
            if (tracks is List && tracks.length == 3) {
              for (var i = 0; i < 3; i++) {
                final track = tracks[i];
                if (track is String) {
                  _favoriteTracks[i].text =
                      track.substring(0, track.length > 100 ? 100 : track.length);
                }
              }
            }
            if (temperature is num && temperature.isFinite &&
                temperature >= 18 && temperature <= 26 &&
                temperature == temperature.roundToDouble()) {
              _cabinTemperature = temperature.toDouble();
            }
            _meetSign = data['meetSign'] == true;
            _pets = data['pets'] == true;
            _soberDriver = data['soberDriver'] == true;
            _flowers = data['flowers'] == true;
            _coffee = data['coffee'] == true;
            _water = data['water'] == true;
            _quietRide = data['quietRide'] == true;
            _luggageHelp = data['luggageHelp'] == true;
            _music = data['music'] == true;
            if (_quietRide) {
              _music = false;
              _radioStation = 'Без радио';
            } else if (_radioStation != 'Без радио') {
              _music = true;
            }
            if (wishes is String) {
              _tripWishes.text =
                  wishes.substring(0, wishes.length > 500 ? 500 : wishes.length);
            }
          });
        }
      } catch (_) {
        // Reject malformed snapshots without blocking the passenger screen.
      }
    }
    _restoringPreferences = false;
    _preferencesReady = true;
    _lastPreferencesSnapshot = jsonEncode(_preferencesSnapshot());
  }

  @override
  void setState(VoidCallback fn) {
    super.setState(fn);
    _savePreferences();
  }


  LatLng? _resolve(String address) =>
      _resolvedAddresses[address.trim()] ?? _places[address.trim()];

  // Common Lithuanian/English names should work even when Photon is offline.
  static const _addressAliases = <String, String>{
    'vilnius airport': 'Аэропорт Вильнюса',
    'vno': 'Аэропорт Вильнюса',
    'vilniaus oro uostas': 'Аэропорт Вильнюса',
    'vilnius': 'Вильнюс',
    'vilnius city': 'Вильнюс',
    'kaunas': 'Каунас',
    'klaipeda': 'Клайпеда',
    'klaipėda': 'Клайпеда',
    'palanga': 'Паланга',
    'trakai': 'Тракай',
    'warsaw': 'Варшава',
    'warszawa': 'Варшава',
  };

  List<String> _localAddressMatches(String query) {
    if (query.isEmpty) return const [];
    final needle = query.toLowerCase();
    final results = <String>{};
    for (final name in _places.keys) {
      if (name.toLowerCase().contains(needle)) results.add(name);
    }
    for (final entry in _addressAliases.entries) {
      if (entry.key.contains(needle)) results.add(entry.value);
    }
    return results.take(5).toList();
  }

  void _addressChanged(String side) {
    _addressTimer?.cancel();
    final query = (side == 'from' ? _from.text : _to.text).trim();
    if (side == 'from') _pickedPickup = null;
    setState(() {
      _route = '';
      _roadPoints = const [];
      _roadDistanceMetres = null;
      _routeInfo = '';
      _editingAddress = side;
      _addressSuggestions = _localAddressMatches(query);
      _addressSearchError = null;
    });
    ++_addressGeneration;
    if (query.length < 3 || !widget.enableMapTiles) return;
    final current = _addressGeneration;
    // The public Photon demo throttles rapid requests. Do not flood it
    // while someone enters each letter of a street or house number.
    _addressTimer = Timer(const Duration(milliseconds: 1100), () async {
      try {
        final uri = Uri.https('photon.komoot.io', '/api/', {
          'q': query, 'limit': '5', 'lang': 'en',
          'lat': '54.6872', 'lon': '25.2797',
        });
        final payload = await const PdHttpApi().getJson(
          uri, timeout: const Duration(seconds: 9));
        final found = <String>[];
        for (final raw in (payload['features'] as List<dynamic>? ?? const [])) {
          final feature = raw as Map<String, dynamic>;
          final p = feature['properties'] as Map<String, dynamic>? ?? {};
          final geometry = feature['geometry'] as Map<String, dynamic>? ?? {};
          final coords = geometry['coordinates'] as List<dynamic>?;
          if (coords == null || coords.length < 2) continue;
          final name = [p['name'],p['street'],p['housenumber'],p['city'],p['country']]
            .whereType<String>().where((v)=>v.trim().isNotEmpty).toSet().join(', ');
          if (name.isEmpty) continue;
          _resolvedAddresses[name] = LatLng((coords[1] as num).toDouble(),
            (coords[0] as num).toDouble());
          found.add(name);
        }
        if (mounted && current == _addressGeneration && _editingAddress == side) {
          setState(() {
            _addressSuggestions = {..._localAddressMatches(query), ...found}
                .take(5).toList();
            _addressSearchError = null;
          });
        }
      } catch (error) {
        debugPrint('PD_ADDRESS_LOOKUP_FAILED: ${error.runtimeType}');
        if (mounted && current == _addressGeneration && _editingAddress == side) {
          setState(() {
            // A lookup failure must not hide working offline destinations.
            if (_addressSuggestions.isEmpty) {
              _addressSearchError = 'Поиск улиц и домов временно недоступен. '
                  'Проверь подключение и нажми «Повторить поиск».';
            } else {
              _addressSearchError = null;
            }
          });
        }
      }
    });
  }

  Future<LatLng> _readDevicePosition() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw StateError('GPS выключен');
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw StateError('Нет разрешения на геолокацию');
    }
    final pos = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 18)));
    return LatLng(pos.latitude, pos.longitude);
  }

  Future<void> _locatePassenger() async {
    if (_findingPassenger) return;
    setState(() { _findingPassenger = true; _locationMessage = null; });
    try {
      final point = await (widget.currentPositionLoader?.call() ??
          _readDevicePosition()).timeout(const Duration(seconds: 22));
      if (!mounted) return;
      if (!point.latitude.isFinite || !point.longitude.isFinite ||
          point.latitude.abs() > 90 || point.longitude.abs() > 180) {
        throw const FormatException('Некорректные координаты GPS');
      }
      setState(() => _passengerLocation = point);
      if (widget.enableMapTiles) _passengerMapController.move(point, 16);
    } catch (_) {
      if (mounted) setState(() => _locationMessage =
        'Не удалось определить местоположение. Проверь GPS и разрешение в настройках.');
    } finally {
      if (mounted) setState(() => _findingPassenger = false);
    }
  }

  void _usePickupPoint(LatLng point) {
    if (!point.latitude.isFinite || !point.longitude.isFinite ||
        point.latitude.abs() > 90 || point.longitude.abs() > 180) return;
    final label = '${point.latitude.toStringAsFixed(6)}, ${point.longitude.toStringAsFixed(6)}';
    _addressTimer?.cancel();
    ++_addressGeneration;
    setState(() {
      _pickedPickup = point;
      _resolvedAddresses[label] = point;
      _from.text = label;
      _editingAddress = null;
      _addressSuggestions = const [];
      _addressSearchError = null;
      _route = '';
      _roadPoints = const [];
      _routeInfo = '';
    });
    unawaited(_updateRoadPreview());
  }

  void _selectAddress(String value, String side) {
    setState(() {
      (side == 'from' ? _from : _to).text = value;
      if (side == 'from') _pickedPickup = null;
      _editingAddress = null;
      _addressSuggestions = const [];
      _route = '';
      _roadPoints = const [];
      _routeInfo = '';
    });
    _addressTimer?.cancel();
    ++_addressGeneration;
    _updateRoadPreview();
  }

  void _openPassengerSection(String section) {
    Navigator.pop(context);
    setState(() => _menuSection = section);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_passengerSheetController.isAttached) return;
      _passengerSheetController.animateTo(0.94,
        duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    });
  }

  Widget _addressSuggestionsWidget(String side) {
    if (_editingAddress != side) return const SizedBox.shrink();
    return Column(children: [
      for (var i = 0; i < _addressSuggestions.length; i++)
        ListTile(
          key: Key('passenger-$side-suggestion-$i'),
          dense: true,
          leading: const Icon(Icons.place_outlined),
          title: Text(_addressSuggestions[i], maxLines: 2),
          onTap: () => _selectAddress(_addressSuggestions[i], side),
        ),
      if (_addressSearchError != null)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          child: Column(children: [
            Text(_addressSearchError!,
              key: const Key('passenger-address-search-error'),
              style: const TextStyle(fontSize: 12, color: Colors.orange)),
            TextButton.icon(
              key: const Key('passenger-retry-address-search'),
              onPressed: () => _addressChanged(side),
              icon: const Icon(Icons.refresh),
              label: Text(pdLabel(context, 'Повторить поиск')),
            ),
          ]),
        ),
    ]);
  }


  @override
  void initState() {
    super.initState();
    _rideType = widget.initialRideType == 'Такси' ? 'Такси' : 'Трансфер';
    _taxiAdvanceBooking = widget.initialAdvanceBooking && _rideType == 'Такси';
    _date = widget.initialAdvanceDate;
    _time = widget.initialAdvanceTime;
    if (widget.enableMapTiles) {
      unawaited(_checkMapNetwork());
    }
    _knownPilotMessageCount = widget.tripStore?.pilotChatMessages.length ?? 0;
    widget.tripStore?.addListener(_onTripChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(_updatePickupEta());
    });
    _tripWishes.addListener(_savePreferences);
    for (final track in _favoriteTracks) {
      track.addListener(_savePreferences);
    }
    unawaited(_restorePreferences());
    if (widget.tripStore != null) {
      _gpsFreshnessTimer = Timer.periodic(const Duration(seconds: 15), (_) {
        if (mounted && widget.tripStore?.pilotLastSeen != null) {
          setState(() {}); // Hide stale pilot fixes even without new GPS events.
          unawaited(_updatePickupEta());
        }
      });
    }
  }

  int _knownPilotMessageCount = 0;

  void _onTripChanged() {
    if (!mounted) return;
    _scheduleFollowPilot();
    unawaited(_updatePickupEta());
    final messages = widget.tripStore?.pilotChatMessages ?? const <String>[];
    if (messages.length > _knownPilotMessageCount) {
      if (widget.onIncomingMessageVoice != null) {
        widget.onIncomingMessageVoice!();
      } else {
        unawaited(PdMessageVoice.announce('пилота'));
      }
      final latest = messages.last;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || ModalRoute.of(context)?.isCurrent != true) return;
        ScaffoldMessenger.of(context).hideCurrentSnackBar();
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          key: const Key('passenger-pilot-message-popup'),
          content: Text('Сообщение пилота: $latest'),
          action: SnackBarAction(
            label: 'Открыть',
            onPressed: () => _openOrders(),
          ),
        ));
      });
    }
    _knownPilotMessageCount = messages.length;
    setState(() {});
  }

  /// Camera follows verified fresh pilot fixes, not synthetic city centres.
  /// Never reset the user's route or selected pickup point while following.
  void _scheduleFollowPilot() {
    final store = widget.tripStore;
    final seen = store?.pilotLastSeen;
    if (!widget.enableMapTiles || !_followPilot || store == null ||
        !store.isActive || !store.pilotOnline || seen == null ||
        DateTime.now().difference(seen) >= const Duration(minutes: 2) ||
        store.pilotLatitude == null || store.pilotLongitude == null) return;
    final point = LatLng(store.pilotLatitude!, store.pilotLongitude!);
    if (_lastPilotCameraFix == point) return;
    _lastPilotCameraFix = point;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_followPilot || !widget.enableMapTiles) return;
      try {
        _passengerMapController.move(point, _passengerMapController.camera.zoom);
      } catch (_) {
        // Map may not be attached when navigating to another screen.
      }
    });
  }

  void _openOrders() {
    final store = widget.tripStore;
    if (store == null) return;
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => PdPassengerLanguageScope(
        child: PassengerOrdersDemo(tripStore: store))));
  }

  void _createLocalTrip() {
    final store = widget.tripStore;
    if (store == null || store.isActive || _cashBlockedForAdvance) return;
    final date = _date ?? DateUtils.dateOnly(DateTime.now());
    final time = _time ?? TimeOfDay.now();
    final departure = DateTime(date.year, date.month, date.day,
        time.hour, time.minute);
    store.create(
      from: _from.text,
      to: _to.text,
      paymentMethod: _payment,
      advanceBooking: _isAdvanceBooking,
      departure: departure,
      rideType: _rideType,
      roundTrip: _roundTrip,
      estimatedFareEur: _rideType == 'Такси' ? null : _pricePreview,
      estimatedFareCents: _taxiPriceCents,
      extrasRequireQuote: _requiresCustomQuote,
      services: [
        if (_rideType == 'Такси' && _taxiAdvanceBooking)
          'Предварительное бронирование +3 €',
        if (_rideType == 'Такси' && _taxiOutsideCity)
          'Тариф за городом 0,79 €/км',
        if (_meetSign) 'Встреча с табличкой',
        if (_pets) 'Животные',
        if (_soberDriver) 'Трезвый водитель',
        if (_music) 'Музыка в дорогу',
        if (_radioStation != 'Без радио') 'Радио: $_radioStation',
        for (var i = 0; i < _favoriteTracks.length; i++)
          if (_favoriteTracks[i].text.trim().isNotEmpty)
            'Любимый трек ${i + 1}: ${_favoriteTracks[i].text.trim()}',
        if (_cabinTemperature != null)
          'Желаемая температура салона: ${_cabinTemperature!.toStringAsFixed(0)} °C',
        if (_flowers) 'Цветы',
        if (_coffee) 'Кофе',
        if (_water) 'Питьевая вода',
        if (_quietRide) 'Тихая поездка',
        if (_luggageHelp) 'Помощь с багажом',
        if (_tripWishes.text.trim().isNotEmpty)
          'Пожелания пассажира: ${_tripWishes.text.trim()}',
      ],
    );
  }

  bool get _isAdvanceBooking => _taxiAdvanceBooking || _date != null || _time != null;

  bool get _cashBlockedForAdvance =>
      _isAdvanceBooking && _payment == 'Наличные';

  bool get _canCreateLocalTrip {
    final store = widget.tripStore;
    final a = _from.text.trim();
    final b = _to.text.trim();
    return store != null && !store.isActive && !_cashBlockedForAdvance &&
        a.isNotEmpty &&
        b.isNotEmpty && a.toLowerCase() != b.toLowerCase();
  }

  static const _places = <String, LatLng>{
    'Вильнюс': LatLng(54.6872, 25.2797),
    'Каунас': LatLng(54.8985, 23.9036),
    'Клайпеда': LatLng(55.7033, 21.1443),
    'Паланга': LatLng(55.9175, 21.0686),
    'Тракай': LatLng(54.6389, 24.9342),
    'Варшава': LatLng(52.2297, 21.0122),
    'Аэропорт Вильнюса': LatLng(54.6341, 25.2858),
  };

  // Approved one-way Sedan tariffs, without 10% discount.
  static const _transferFares = <String, int>{
    'вильнюс|аэропорт вильнюса': 40,
    'аэропорт вильнюса|вильнюс': 40,
    'вильнюс|каунас': 110,
    'вильнюс|клайпеда': 230,
    'вильнюс|паневежис': 120,
    'вильнюс|кедайняй': 130,
    'вильнюс|шяуляй': 200,
    'вильнюс|мариямполе': 130,
    'вильнюс|алитус': 100,
    'вильнюс|друскининкай': 120,
    'вильнюс|бирштонас': 90,
    'вильнюс|утена': 115,
    'вильнюс|кибартай': 160,
    'вильнюс|панямуне': 200,
    'вильнюс|рига': 250,
    'вильнюс|варшава': 400,
  };

  int? get _fixedPrice {
    final a = _from.text.trim().toLowerCase();
    final b = _to.text.trim().toLowerCase();
    if (_rideType == 'Такси') return null;
    if (_rideType != 'Трансфер') return null;
    if (_roundTrip) return a == 'вильнюс' && b == 'каунас' ? 200 : null;
    return _transferFares['$a|$b'];
  }

  // Only approved amounts enter the preview. Unpriced requests never
  // silently become free and never erase the known fare.
  bool get _requiresCustomQuote => _pets || _flowers || _coffee || _water;

  int? get _taxiPriceCents {
    if (_rideType != 'Такси' || _roadDistanceMetres == null) return null;
    final base = PdTaxiFare.calculate(
      cityMetres: _taxiOutsideCity ? 0 : _roadDistanceMetres!,
      outsideCityMetres: _taxiOutsideCity ? _roadDistanceMetres! : 0,
      advanceBooking: _taxiAdvanceBooking);
    return base * (_soberDriver ? 2 : 1) + (_meetSign ? 1500 : 0);
  }

  int? get _pricePreview {
    final fixed = _fixedPrice;
    if (fixed == null) return null;
    // Sober driver: approved double base fare; meet-and-greet stays +15 EUR.
    return fixed * (_soberDriver ? 2 : 1) + (_meetSign ? 15 : 0);
  }

  // Vilnius FM frequencies (no playback, preference only).
  static const _vilniusRadio = <String>[
    'Без радио',
    'M-1 · 106,8 FM',
    'M-1 Plius · 106,2 FM',
    'Radiocentras · 89,6 FM',
    'Power Hit Radio · 95,9 FM',
    'ZIP FM · 100,1 FM',
    'Lietus · 103,1 FM',
    'Relax FM · 96,4 FM',
    'LRT RADIJAS · 89,0 FM',
  ];

  /// Public routing service is used only for a preview of preset city routes.
  /// Failure is displayed explicitly; never pretend a straight line is a road.
  Future<void> _updateRoadPreview() async {
    final request = ++_routeRequest;
    final start = _resolve(_from.text);
    final finish = _resolve(_to.text);
    _roadDistanceMetres = null;
    if (start == null || finish == null || !widget.enableMapTiles) {
      if (mounted) setState(() {
        _roadPoints = const [];
        _routeLoading = false;
        _routeInfo = start == null || finish == null
            ? 'Для своего адреса требуется подключение поиска адресов.'
            : '';
      });
      return;
    }
    setState(() {
      _routeLoading = true;
      _roadPoints = const [];
      _routeInfo = 'Построение дорожного маршрута · демо…';
    });
    try {
      final uri = Uri.https('router.project-osrm.org',
          '/route/v1/driving/${start.longitude},${start.latitude};${finish.longitude},${finish.latitude}',
          {'overview': 'full', 'geometries': 'geojson'});
      final decoded = await const PdHttpApi().getJson(
          uri, timeout: const Duration(seconds: 8));
      final routes = decoded['routes'] as List<dynamic>?;
      if (routes == null || routes.isEmpty) throw const FormatException('No road route');
      final route = routes.first as Map<String, dynamic>;
      final coordinates = (route['geometry'] as Map<String, dynamic>)['coordinates']
          as List<dynamic>;
      final points = coordinates.map((raw) {
        final p = raw as List<dynamic>;
        return LatLng((p[1] as num).toDouble(), (p[0] as num).toDouble());
      }).toList(growable: false);
      if (points.length < 2) throw const FormatException('Empty road route');
      if (!mounted || request != _routeRequest) return;
      setState(() {
        _roadPoints = points;
        _roadDistanceMetres = (route['distance'] as num).round();
        _routeLoading = false;
        final km = ((route['distance'] as num).toDouble() / 1000).round();
        _routeInfo = 'Дорожный маршрут · около $km км · демо';
      });
    } catch (_) {
      if (!mounted || request != _routeRequest) return;
      setState(() {
        _roadPoints = const [];
        _roadDistanceMetres = null;
        _routeLoading = false;
        _routeInfo = 'Дорожный маршрут временно недоступен.';
      });
    }
  }

  void _chooseRoute(String route, String from, String to) {
    setState(() {
      _route = route;
      _from.text = from;
      _to.text = to;
    });
    _updateRoadPreview();
  }

  Future<void> _pickDate() async {
    final today = DateUtils.dateOnly(DateTime.now());
    final selected = await showDatePicker(
      context: context,
      initialDate: _date ?? today,
      firstDate: today,
      lastDate: today.add(const Duration(days: 365)),
    );
    if (selected != null && mounted && widget.tripStore?.isActive != true) setState(() {
      _date = selected;
      if (_cashBlockedForAdvance) _payment = 'Карта';
    });
  }

  Future<void> _pickTime() async {
    final selected = await showTimePicker(
      context: context,
      initialTime: _time ?? TimeOfDay.now(),
    );
    if (selected != null && mounted && widget.tripStore?.isActive != true) setState(() {
      _time = selected;
      if (_cashBlockedForAdvance) _payment = 'Карта';
    });
  }

  // Independent of flutter_map's image pipeline: surfaces DNS/TLS/HTTP errors
  // that otherwise look like a blank map on some Android devices.
  Future<void> _checkMapNetwork() async {
    if (!widget.enableMapTiles || _checkingMapNetwork) return;
    if (mounted) setState(() {
      _checkingMapNetwork = true;
      _mapNetworkError = null;
    });
    if (widget.mapConnectivityCheck != null) {
      try {
        final issue = await widget.mapConnectivityCheck!();
        if (mounted) setState(() {
          _mapNetworkError = issue;
          if (issue == null) _mapTilesFailed = false;
        });
      } on Exception {
        if (mounted) setState(() =>
            _mapNetworkError = 'Тестовая проверка карты не удалась');
      } finally {
        if (mounted) setState(() => _checkingMapNetwork = false);
      }
      return;
    }
    // Browser image elements may display OSM tiles even when cross-origin
    // fetch() is blocked by CORS (notably on iPhone Safari). Do not use a
    // binary HTTP probe to decide whether the browser can render the map.
    // TileLayer's errorTileCallback remains the actual visual health check.
    if (kIsWeb) {
      if (mounted) setState(() {
        _checkingMapNetwork = false;
        _mapNetworkError = null;
      });
      return;
    }
    final client = http.Client();
    try {
      final uri = Uri.parse(
        'https://tile.openstreetmap.org/10/583/325.png');
      final response = await client.get(uri).timeout(const Duration(seconds: 7));
      if (response.statusCode != 200 ||
          !response.headers['content-type'].toString().contains('image/png')) {
        throw Exception('HTTP ${response.statusCode}');
      }
      if (response.bodyBytes.isEmpty) {
        throw const FormatException('Пустое изображение');
      }
      if (mounted) setState(() {
        _mapNetworkError = null;
        _mapTilesFailed = false;
      });
    } on Exception catch (error) {
      // A direct OSM probe may fail on the device even when alternate OSM tiles work.
      // Switch providers rather than covering an otherwise usable map.
      if (mounted) setState(() {
        _lastTileError = 'Сеть: ${error.runtimeType}';
        if (!_useBackupTiles) {
          _useBackupTiles = true;
          _mapTileErrors = 0;
          _tileRetry++;
        }
      });
    } finally {
      client.close();
      if (mounted) setState(() => _checkingMapNetwork = false);
    }
  }

  void _retryMap() {
    setState(() {
      _mapTilesFailed = false;
      _mapNetworkError = null;
      _mapTileErrors = 0;
      _useBackupTiles = false;
      _lastTileError = null;
      _tileRetry++;
    });
    unawaited(_checkMapNetwork());
  }

  @override
  void dispose() {
    widget.tripStore?.removeListener(_onTripChanged);
    _routeRequest++;
    _pickupEtaGeneration++;
    _addressTimer?.cancel();
    _gpsFreshnessTimer?.cancel();
    if (widget.passengerMapController == null) _passengerMapController.dispose();
    _from.dispose();
    _to.dispose();
    _tripWishes.removeListener(_savePreferences);
    _tripWishes.dispose();
    for (final track in _favoriteTracks) {
      track.removeListener(_savePreferences);
      track.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    final start = _resolve(_from.text);
    final finish = _resolve(_to.text);
    final store = widget.tripStore;
    final lastFix = store?.pilotLastSeen;
    final showPilot = store != null && store.isActive &&
        store.pilotOnline && store.pilotLatitude != null &&
        store.pilotLongitude != null && lastFix != null &&
        !lastFix.isAfter(DateTime.now()) &&
        DateTime.now().difference(lastFix) < const Duration(minutes: 2);
    final pilotPosition = showPilot
        ? LatLng(store.pilotLatitude!, store.pilotLongitude!)
        : null;
    if (pilotPosition != null) _scheduleFollowPilot();
    final price = _pricePreview;
    final taxiPrice = _taxiPriceCents;
    final startMap = start != null && finish != null
        ? LatLng((start.latitude + finish.latitude) / 2,
            (start.longitude + finish.longitude) / 2)
        : start ?? const LatLng(54.6872, 25.2797);
    final mapGeneration = _tileRetry;
    final mapZoom = start != null && finish != null
        ? (start.longitude - finish.longitude).abs() > 2 ? 6.3 : 8.2
        : 10.0;
    final mapMarkers = <Marker>[
      if (_passengerLocation != null)
        Marker(point: _passengerLocation!, width: 42, height: 42,
          child: const Icon(Icons.my_location, color: Colors.lightBlueAccent,
            key: Key('passenger-gps-marker'), size: 30)),
      if (_pickedPickup != null)
        Marker(point: _pickedPickup!, width: 45, height: 45,
          child: const Icon(Icons.place, color: Colors.amber,
            key: Key('passenger-picked-pickup-marker'), size: 36)),
      if (start != null && _pickedPickup == null)
        Marker(
          point: start,
          width: 48,
          height: 48,
          child: const Icon(Icons.trip_origin, color: gold, size: 32),
        ),
      if (finish != null)
        Marker(
          point: finish,
          width: 48,
          height: 48,
          child: const Icon(Icons.location_on, color: Colors.redAccent, size: 34),
        ),
      if (pilotPosition != null)
        Marker(
          point: pilotPosition,
          width: 52,
          height: 52,
          child: const Icon(
            Icons.location_on,
            key: Key('passenger-pilot-map-marker'),
            color: Color(0xFFB6FF36),
            size: 46,
            shadows: [
              Shadow(color: Colors.black, blurRadius: 8),
              Shadow(color: Color(0xFF355100), blurRadius: 3),
            ],
          ),
        ),
    ];

    Widget passengerMap() => SizedBox.expand(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    widget.enableMapTiles
                    ? KeyedSubtree(
                        key: const ValueKey('passenger-route-map-persistent-controller'),
                        child: FlutterMap(
                        key: const Key('passenger-map'),
                        mapController: _passengerMapController,
                        options: MapOptions(
                          onTap: (_, point) => _usePickupPoint(point),
                          initialCenter: startMap,
                          initialZoom: mapZoom,
                          backgroundColor: _nightMap
                              ? const Color(0xFF101B2B)
                              : const Color(0xFFE0EAF0),
                        ),
                        children: [
                          KeyedSubtree(
                            key: ValueKey('passenger-raster-tile-generation-$mapGeneration'),
                            child: ColorFiltered(
                            key: const Key('passenger-map-night-filter'),
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
                            key: const Key('passenger-map-tiles'),
                            tileProvider: demoTileProvider(),
                            // Both modes use keyless OSM raster tiles; fallback is for isolated tests.
                            urlTemplate: PdMapboxQaConfig.rasterTileUrl ??
                                (_useBackupTiles
                                    ? 'https://tile.openstreetmap.de/{z}/{x}/{y}.png'
                                    : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'),
                            userAgentPackageName: 'lt.privatedrive.privateDrive.demo',
                            errorTileCallback: (tile, error, stackTrace) {
                              debugPrint('PD_PASSENGER_TILE_ERROR: $error');
                              WidgetsBinding.instance.addPostFrameCallback((_) {
                                if (!mounted || _mapTilesFailed ||
                                    mapGeneration != _tileRetry ||
                                    // Keep explicitly injected network errors
                                    // visible in deterministic widget tests.
                                    (widget.mapConnectivityCheck != null &&
                                     _mapNetworkError != null)) return;
                                setState(() {
                                  _lastTileError = error.toString();
                                  _mapTileErrors++;
                                  if (_mapTileErrors >= 3) {
                                    if (!_useBackupTiles) {
                                      // Temporary Safari test fallback: OSM.de requires no CARTO API key;
                                      // retry automatically with CARTO light.
                                      _useBackupTiles = true;
                                      _mapTileErrors = 0;
                                      _mapNetworkError = null;
                                      _tileRetry++;
                                    } else {
                                      _mapTilesFailed = true;
                                    }
                                  }
                                });
                              });
                            },
                            ),
                            ),
                          ),
                          if (_roadPoints.isNotEmpty)
                            PolylineLayer(
                              key: const Key('passenger-road-route'),
                              polylines: [
                                Polyline(
                                  points: _roadPoints,
                                  color: gold,
                                  strokeWidth: 5,
                                ),
                              ],
                            ),
                          MarkerLayer(markers: mapMarkers),
                          const RichAttributionWidget(
                            attributions: [
                              TextSourceAttribution('© OpenStreetMap contributors'),
                              TextSourceAttribution('© OpenStreetMap.de'),
                            ],
                          ),
                        ],
                        ),
                      )
                    : const ColoredBox(
                        key: Key('passenger-map'),
                        color: Color(0xFF27332F),
                        child: Center(child: Text('Карта · офлайн-тест')),
                      ),
                    if (widget.enableMapTiles &&
                        (_mapTilesFailed || _mapNetworkError != null))
                      Positioned.fill(
                        child: ColoredBox(
                          color: const Color(0xF01A2A34),
                          child: Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.map_outlined,
                                  color: Color(0xFFDDC184), size: 42),
                                const SizedBox(height: 8),
                                Text(pdLabel(context, 'Карта временно недоступна'),
                                  key: Key('passenger-map-load-error')),
                                Text(_mapNetworkError ?? _lastTileError ??
                                    'Не удалось показать тайлы карты',
                                  key: const Key('passenger-map-error-details'),
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(fontSize: 12)),
                                TextButton.icon(
                                  key: const Key('passenger-map-retry'),
                                  onPressed: _retryMap,
                                  icon: const Icon(Icons.refresh),
                                  label: Text(pdLabel(context, 'Повторить загрузку')),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    if (widget.enableMapTiles && _checkingMapNetwork &&
                        !_mapTilesFailed)
                      const Positioned(
                        left: 8, bottom: 8,
                        child: Text('Проверка сервера карты…',
                          key: Key('passenger-map-checking'),
                          style: TextStyle(color: Colors.white, fontSize: 11)),
                      ),
                    Positioned(
                      top: 8, left: 8,
                      child: Material(
                        color: const Color(0xF0172535),
                        borderRadius: BorderRadius.circular(12),
                        child: IconButton(
                          key: const Key('passenger-locate-me'),
                          tooltip: pdTr(context, 'Моё местоположение',
                            'Mano vieta', 'My location'),
                          onPressed: _findingPassenger ? null : _locatePassenger,
                          icon: _findingPassenger
                            ? const SizedBox(width: 18, height: 18,
                                child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.my_location, color: gold),
                        ),
                      ),
                    ),
                    if (pilotPosition != null)
                      Positioned(
                        top: 64,
                        right: 8,
                        child: Material(
                          color: const Color(0xF0172535),
                          borderRadius: BorderRadius.circular(12),
                          child: IconButton(
                            key: const Key('passenger-follow-pilot'),
                            tooltip: _followPilot
                              ? 'Остановить слежение за пилотом'
                              : 'Следить за пилотом',
                            icon: Icon(_followPilot
                              ? Icons.gps_fixed : Icons.gps_not_fixed,
                              color: const Color(0xFFDDC184)),
                            onPressed: () {
                              setState(() {
                                _followPilot = !_followPilot;
                                _lastPilotCameraFix = null;
                              });
                              if (_followPilot) _scheduleFollowPilot();
                            },
                          ),
                        ),
                      ),
                    Positioned(
                      top: 8,
                      right: 8,
                      child: Material(
                        color: const Color(0xF0172535),
                        borderRadius: BorderRadius.circular(12),
                        child: IconButton(
                          key: const Key('passenger-map-day-night'),
                          tooltip: pdLabel(context, _nightMap ? 'Дневная карта' : 'Ночная карта'),
                          icon: Icon(_nightMap ? Icons.wb_sunny_outlined
                              : Icons.dark_mode_outlined,
                              color: const Color(0xFFDDC184), size: 20),
                          onPressed: () => setState(() {
                            _nightMap = !_nightMap;
                            _mapTileErrors = 0;
                            _mapTilesFailed = false;
                            _lastTileError = null;
                            _tileRetry++;
                          }),
                          ),
                      ),
                    ),
                  ],
                ),
              ),
            );

    Widget bookingForm(ScrollController? panelScrollController) =>
      ListView(
                controller: panelScrollController,
                key: const Key('passenger-form'),
          padding: const EdgeInsets.all(16),
          children: [
            if (widget.tripStore?.pilotChatMessages.isNotEmpty == true)
              Card(
                key: const Key('passenger-pilot-message-alert'),
                child: ListTile(
                  leading: const Icon(Icons.mark_chat_unread_outlined),
                  title: Text(pdLabel(context, 'Сообщение от пилота')),
                  subtitle: Text(widget.tripStore!.pilotChatMessages.last,
                    maxLines: 2, overflow: TextOverflow.ellipsis),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: _openOrders,
                ),
              ),
            if (widget.initialAdvanceBooking) ...[
              Card(
                key: const Key('passenger-advance-booking-banner'),
                color: const Color(0xFF46371A),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(children: [
                    const Icon(Icons.event_available_outlined, color: Color(0xFFE5C57B)),
                    const SizedBox(width: 10),
                    Expanded(child: Text(pdTr(context,
                        'Предварительный заказ: укажи адрес, дату и время',
                        'Išankstinis užsakymas: nurodyk adresą, datą ir laiką',
                        'Advance booking: choose address, date and time'),
                      style: const TextStyle(fontWeight: FontWeight.bold))),
                  ]),
                ),
              ),
              const SizedBox(height: 8),
            ],
            Text(pdLabel(context, 'Тестовый заказ поездки'), style: TextStyle(fontSize: 22)),
            const SizedBox(height: 6),
            Text(pdLabel(context, 'Демонстрация. Не отправляет заказы и не списывает деньги.')),
            const SizedBox(height: 12),
            Text('${pdLabel(context, _rideType)} · ${pdLabel(context, 'выбранный тип поездки')}',
              key: const Key('passenger-selected-ride-type'),
              style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            if (_rideType == 'Трансфер') ...[
              SwitchListTile(
                key: const Key('passenger-round-trip'),
                title: Text(pdLabel(context, 'Туда и обратно')),
                value: _roundTrip,
                onChanged: widget.tripStore?.isActive == true ? null : (v) => setState(() => _roundTrip = v),
              ),
              Text(
                pdTr(context,
                  'Фиксированные тарифы Sedan без скидки: '
                  'Вильнюс → Каунас 110 €, '
                  'Вильнюс ↔ аэропорт Вильнюса 40 €. '
                  'Вильнюс — Каунас туда и обратно 200 €. '
                  'Другие маршруты — по тарифной таблице или по запросу.',
                  'Fiksuotos Sedan kainos be nuolaidos: Vilnius → Kaunas 110 €, '
                  'Vilnius ↔ Vilniaus oro uostas 40 €. '
                  'Vilnius–Kaunas į abi puses 200 €. Kiti maršrutai pagal kainoraštį arba užklausą.',
                  'Fixed Sedan fares with no discount: Vilnius → Kaunas €110, '
                  'Vilnius ↔ Vilnius Airport €40. '
                  'Vilnius–Kaunas round trip €200. Other routes per price list or on request.'),
                key: const Key('passenger-transfer-tariffs'),
                style: const TextStyle(fontSize: 12),
              ),
            ] else ...[
              const Text(
                'Такси: посадка 0,99 € · город 0,66 €/км · '
                'за городом 0,79 €/км · минимум 4 €. '
                'Расчёт только по подтверждённому дорожному маршруту.',
                key: Key('passenger-taxi-tariffs'),
                style: TextStyle(fontSize: 12),
              ),
              SwitchListTile(
                key: const Key('taxi-outside-city'),
                title: const Text('Тариф поездки за городом · 0,79 €/км'),
                subtitle: const Text('Весь рассчитанный маршрут по ставке за городом. '
                    'Для смешанного маршрута стоимость уточняет диспетчер.'),
                value: _taxiOutsideCity,
                onChanged: widget.tripStore?.isActive == true ? null : (v) => setState(() => _taxiOutsideCity = v),
              ),
              CheckboxListTile(
                key: const Key('taxi-advance-booking'),
                title: const Text('Предварительное бронирование · +3 €'),
                value: _taxiAdvanceBooking,
                onChanged: widget.tripStore?.isActive == true ? null : (v) => setState(() {
                  _taxiAdvanceBooking = v ?? false;
                  if (_cashBlockedForAdvance) _payment = 'Карта';
                }),
              ),
            ],
            const SizedBox(height: 12),
            if (!widget.enableMapTiles)
              SizedBox(height: 285, child: passengerMap()),
            if (_locationMessage != null)
              Text(_locationMessage!, key: const Key('passenger-location-error'),
                style: const TextStyle(color: Colors.orangeAccent)),
            if (_passengerLocation != null)
              OutlinedButton.icon(
                key: const Key('passenger-use-current-as-pickup'),
                onPressed: () => _usePickupPoint(_passengerLocation!),
                icon: const Icon(Icons.trip_origin),
                label: Text(pdTr(context, 'Забрать меня здесь',
                  'Paimti mane čia', 'Pick me up here')),
              ),
            Text(pdTr(context, 'Нажми на карту, чтобы выбрать точку посадки.',
              'Paliesk žemėlapį, kad pasirinktum paėmimo vietą.',
              'Tap the map to choose your pickup point.'),
              key: const Key('passenger-pickup-map-instruction'),
              style: const TextStyle(fontSize: 12)),
            if (store != null && store.isActive)
              Text(
                store.status == DemoTripStatus.requested
                    ? 'Время подачи: ожидаем назначения пилота'
                    : store.status == DemoTripStatus.assigned &&
                            !store.pilotAccepted
                        ? 'Время подачи: ожидаем подтверждения пилота'
                        : _pickupEtaMinutes != null && pilotPosition != null &&
                                (store.status == DemoTripStatus.assigned ||
                                 store.status == DemoTripStatus.approaching)
                            ? 'Примерное время подачи: ≈ $_pickupEtaMinutes мин · без учёта пробок'
                            : 'Время подачи уточняется',
                key: const Key('passenger-pickup-eta'),
                style: const TextStyle(
                  color: Color(0xFFDDC184), fontWeight: FontWeight.w700,
                ),
              ),
            if (store != null && store.isActive &&
                store.trip?.rideType == 'Такси')
              Text(
                pilotPosition == null ||
                        !(store.status == DemoTripStatus.approaching ||
                          store.status == DemoTripStatus.assigned &&
                          store.pilotAccepted) ||
                        _pickupRoadMetres == null
                    ? 'Дальняя подача: расчёт после выбора пилота и получения дорожного маршрута'
                    : 'Подача по дороге: ${(_pickupRoadMetres! / 1000).toStringAsFixed(1)} км · '
                      'доплата ${PdPickupFee.euros(PdPickupFee.calculateCents(roadMetres: _pickupRoadMetres!))} '
                      '(сверх 5 км по 0,40 €/км). '
                      'Только предварительный расчёт: доплата не включена в заказ и требует согласия пассажира.',
                key: const Key('passenger-long-pickup-quote'),
                style: const TextStyle(
                  color: Color(0xFFDDC184), fontSize: 12,
                ),
              ),
            if (store != null && store.isActive)
              Text(
                pilotPosition != null
                    ? 'Местоположение пилота · GPS обновляется'
                    : 'Местоположение пилота пока недоступно',
                key: const Key('passenger-pilot-location-status'),
                style: const TextStyle(fontSize: 12),
              ),
            if (_routeInfo.isNotEmpty)
              Text(_routeInfo, key: const Key('passenger-route-info'),
                  style: const TextStyle(fontSize: 12)),
            if (_routeLoading)
              const LinearProgressIndicator(key: Key('passenger-route-loading')),
            const SizedBox(height: 12),
            if (!widget.enableMapTiles || _menuSection == 'routes') ...[
            Text(pdLabel(context, 'Популярные направления')),
            Wrap(
              spacing: 6,
              children: [
                ActionChip(
                  key: const Key('route-kaunas'),
                  label: Text(pdLabel(context, 'Вильнюс — Каунас')),
                  onPressed: () => _chooseRoute('Вильнюс — Каунас', 'Вильнюс', 'Каунас'),
                ),
                ActionChip(
                  key: const Key('route-airport'),
                  label: Text(pdLabel(context, 'Аэропорт')),
                  onPressed: () => _chooseRoute('Аэропорт', 'Вильнюс', 'Аэропорт Вильнюса'),
                ),
                ActionChip(
                  key: const Key('route-warsaw'),
                  label: Text(pdLabel(context, 'Вильнюс — Варшава')),
                  onPressed: () => _chooseRoute('Вильнюс — Варшава', 'Вильнюс', 'Варшава'),
                ),
                ActionChip(
                  key: const Key('route-klaipeda'),
                  label: Text(pdLabel(context, 'Вильнюс — Клайпеда')),
                  onPressed: () => _chooseRoute(
                    'Вильнюс — Клайпеда', 'Вильнюс', 'Клайпеда'),
                ),
                ActionChip(
                  key: const Key('route-trakai'),
                  label: Text(pdLabel(context, 'Вильнюс — Тракай')),
                  onPressed: () => _chooseRoute(
                    'Вильнюс — Тракай', 'Вильнюс', 'Тракай'),
                ),
                ActionChip(
                  key: const Key('route-palanga'),
                  label: Text(pdLabel(context, 'Вильнюс — Паланга')),
                  onPressed: () => _chooseRoute('Вильнюс — Паланга', 'Вильнюс', 'Паланга'),
                ),
              ],
            ),
            ],
            TextField(
              key: const Key('passenger-from'),
              controller: _from,
              readOnly: widget.tripStore?.isActive == true,
              onChanged: (_) { _addressChanged('from'); _updateRoadPreview(); },
              decoration: InputDecoration(
                labelText: pdLabel(context, 'Откуда'), prefixIcon: Icon(Icons.trip_origin),
              ),
            ),
            _addressSuggestionsWidget('from'),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('passenger-to'),
                    controller: _to,
                    readOnly: widget.tripStore?.isActive == true,
                    onChanged: (_) { _addressChanged('to'); _updateRoadPreview(); },
                    decoration: InputDecoration(
                      labelText: pdLabel(context, 'Куда'), prefixIcon: Icon(Icons.location_on_outlined),
                    ),
                  ),
                ),
                IconButton(
                  key: const Key('passenger-swap'),
                  tooltip: pdLabel(context, 'Поменять А и Б'),
                  onPressed: widget.tripStore?.isActive == true ? null : () {
                    setState(() {
                      _pickedPickup = null;
                      final previous = _from.text;
                      _from.text = _to.text;
                      _to.text = previous;
                      _route = '';
                      _roadPoints = const [];
                      _routeInfo = '';
                    });
                    _updateRoadPreview();
                  },
                  icon: const Icon(Icons.swap_vert),
                ),
              ],
            ),
            _addressSuggestionsWidget('to'),
            Text(pdTr(context,
              'Адресные подсказки запрашиваются у внешнего сервиса Photon. '
              'Не вводи конфиденциальные адреса в демоверсии.',
              'Adreso pasiūlymai gaunami iš išorinės Photon paslaugos. '
              'Demo versijoje neįveskite konfidencialių adresų.',
              'Address suggestions come from the external Photon service. '
              'Do not enter confidential addresses in the demo.'),
              style: const TextStyle(fontSize: 11)),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    key: const Key('passenger-date'),
                    onPressed: widget.tripStore?.isActive == true ? null : _pickDate,
                    icon: const Icon(Icons.calendar_today),
                    label: Text(_date == null
                        ? pdLabel(context, 'Дата')
                        : '${_date!.day.toString().padLeft(2, '0')}.${_date!.month.toString().padLeft(2, '0')}.${_date!.year}'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    key: const Key('passenger-time'),
                    onPressed: widget.tripStore?.isActive == true ? null : _pickTime,
                    icon: const Icon(Icons.schedule),
                    label: Text(_time == null ? pdLabel(context, 'Время') : _time!.format(context)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            if (widget.tripStore != null) ...[
              Text(pdTr(context, 'Дополнительные услуги',
                  'Papildomos paslaugos', 'Additional services'),
                key: const Key('passenger-booking-extra-services-title'),
                style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Card(child: ListTile(
                key: const Key('passenger-booking-jumpstart'),
                leading: const Icon(Icons.battery_charging_full, size: 32),
                title: Text(pdTr(context, 'Запуск автомобиля · 20 €',
                    'Automobilio užvedimas · 20 €', 'Car jump-start · €20')),
                subtitle: Text(pdTr(context, 'Помощь с разряженным аккумулятором',
                    'Pagalba išsikrovus akumuliatoriui',
                    'Help with a flat car battery')),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.push(context, MaterialPageRoute<void>(
                  builder: (_) => PdPassengerLanguageScope(
                    child: PassengerExtraServices(
                      type: ExtraServiceType.jumpstart,
                      tripStore: widget.tripStore!)))),
              )),
              Card(child: ListTile(
                key: const Key('passenger-booking-delivery'),
                leading: const Icon(Icons.shopping_bag_outlined, size: 32),
                title: Text(pdTr(context, 'Доставка товаров · 20 €',
                    'Prekių pristatymas · 20 €', 'Goods delivery · €20')),
                subtitle: Text(pdTr(context, 'Заберём покупки из магазина и доставим',
                    'Paimsime pirkinius iš parduotuvės ir pristatysime',
                    'We will pick up and deliver your shopping')),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.push(context, MaterialPageRoute<void>(
                  builder: (_) => PdPassengerLanguageScope(
                    child: PassengerExtraServices(
                      type: ExtraServiceType.delivery,
                      tripStore: widget.tripStore!)))),
              )),
            ],
            const SizedBox(height: 16),
            if (!widget.enableMapTiles || _menuSection == 'preferences') ...[
            AbsorbPointer(
              absorbing: widget.tripStore?.isActive == true,
              child: Card(
              key: const Key('passenger-personal-trip-settings-card'),
              child: ExpansionTile(
                key: const Key('passenger-personal-trip-settings'),
                initiallyExpanded: true,
                leading: const Icon(Icons.tune),
                title: Text(pdLabel(context, 'Личные настройки пассажира для поездки')),
                subtitle: Text(pdLabel(context, 'Цветы, кофе, вода, комфорт и пожелания')),
                childrenPadding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
              CheckboxListTile(
                key: const Key('service-meet-sign'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Встреча с табличкой · +15 €')),
                value: _meetSign,
                onChanged: (v) => setState(() => _meetSign = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-pets'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Поездка с животными · цена по запросу')),
                value: _pets,
                onChanged: (v) => setState(() => _pets = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-sober'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Трезвый водитель · ×2 к тарифу')),
                value: _soberDriver,
                onChanged: (v) => setState(() => _soberDriver = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-music'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Музыка в дорогу · бесплатно')),
                value: _music,
                onChanged: (v) => setState(() {
                  _music = v ?? false;
                  if (_music) _quietRide = false;
                   if (!_music) _radioStation = 'Без радио';
                }),
              ),
              CheckboxListTile(
                key: const Key('service-flowers'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Цветы · стоимость по запросу')),
                value: _flowers,
                onChanged: (v) => setState(() => _flowers = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-coffee'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Кофе · стоимость по запросу')),
                value: _coffee,
                onChanged: (v) => setState(() => _coffee = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-water'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Питьевая вода · стоимость уточняется')),
                value: _water,
                onChanged: (v) => setState(() => _water = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-quiet-ride'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Тихая поездка · без музыки и разговоров')),
                value: _quietRide,
                onChanged: (v) => setState(() {
                  _quietRide = v ?? false;
                  if (_quietRide) {
                     _music = false;
                     _radioStation = 'Без радио';
                   }
                }),
              ),
              CheckboxListTile(
                key: const Key('service-luggage-help'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(pdLabel(context, 'Помощь с багажом')),
                value: _luggageHelp,
                onChanged: (v) => setState(() => _luggageHelp = v ?? false),
              ),
              Padding(
                padding: const EdgeInsets.only(top: 12, bottom: 8),
                child: Text(pdLabel(context, 'Комфорт и музыка в дороге'),
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
              DropdownButtonFormField<String>(
                key: ValueKey('passenger-radio-station-$_radioStation'),
                initialValue: _radioStation,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: pdLabel(context, 'Радиостанция · FM-частоты Вильнюса'),
                  border: OutlineInputBorder(),
                ),
                items: _vilniusRadio.map((station) =>
                  DropdownMenuItem(value: station, child: Text(station))).toList(),
                onChanged: (station) => setState(() {
                  _radioStation = station ?? 'Без радио';
                  if (_radioStation != 'Без радио') {
                    _music = true;
                    _quietRide = false;
                  }
                }),
              ),
              const SizedBox(height: 8),
              for (var i = 0; i < _favoriteTracks.length; i++)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: TextField(
                    key: Key('passenger-favorite-track-$i'),
                    controller: _favoriteTracks[i],
                    maxLength: 100,
                    decoration: InputDecoration(
                      labelText: pdTr(context,
                        'Любимый трек ${i + 1} · исполнитель и название',
                        'Mėgstama daina ${i + 1} · atlikėjas ir pavadinimas',
                        'Favorite track ${i + 1} · artist and title'),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
              DropdownButtonFormField<double?>(
                key: ValueKey('passenger-cabin-temperature-$_cabinTemperature'),
                initialValue: _cabinTemperature,
                decoration: InputDecoration(
                  labelText: pdLabel(context, 'Желаемая температура в салоне'),
                  border: OutlineInputBorder(),
                ),
                items: [
                  DropdownMenuItem<double?>(
                    value: null, child: Text(pdLabel(context, 'На усмотрение пилота'))),
                  for (var temp = 18; temp <= 26; temp++)
                    DropdownMenuItem<double?>(
                      value: temp.toDouble(), child: Text('$temp °C')),
                ],
                onChanged: (temperature) =>
                  setState(() => _cabinTemperature = temperature),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('passenger-trip-wishes'),
                controller: _tripWishes,
                maxLength: 500,
                maxLines: 3,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: pdLabel(context, 'Другие пожелания к поездке'),
                  hintText: pdLabel(context, 'Например, вода без газа, тишина или помощь с багажом'),
                  border: OutlineInputBorder(),
                ),
              ),
                ],
              ),
            ),
            ),
            const SizedBox(height: 12),
            ],
            if (!widget.enableMapTiles || _menuSection == 'payments') ...[
            Text(pdLabel(context, 'Способ оплаты · только выбор'), style: TextStyle(fontWeight: FontWeight.bold)),
            Wrap(
              spacing: 8,
              children: [
                for (final method in ['Карта', 'PayPal', 'Банковский перевод', 'Криптовалюта'])
                  ChoiceChip(
                    key: Key('payment-$method'),
                    label: Text(method == 'Карта'
                      ? pdTr(context, 'Карта', 'Kortelė', 'Card')
                      : pdLabel(context, method)),
                    selected: _payment == method,
                    onSelected: widget.tripStore?.isActive == true ||
                        (_isAdvanceBooking && method == 'Наличные') ? null
                        : (_) => setState(() => _payment = method),
                  ),
              ],
            ),
            TextButton.icon(
              key: const Key('passenger-paysera-info'),
              onPressed: _openPayseraPaymentInfo,
              icon: const Icon(Icons.open_in_new),
              label: Text(pdTr(context, 'Оплата через Paysera',
                  'Mokėjimas per „Paysera“', 'Paying with Paysera')),
            ),
            if (_cashBlockedForAdvance)
              const Text(
                'Предварительный заказ оплачивается только безналично. '
                'Выбери карту, PayPal, банковский перевод или криптовалюту.',
                key: Key('advance-cash-payment-blocked'),
                style: TextStyle(color: Colors.orangeAccent),
              ),
            const SizedBox(height: 12),
            ],
            Text(
              ( _rideType == 'Такси' ? taxiPrice == null : price == null )
                  ? pdTr(context,
                      'Стоимость по запросу · фиксированная цена не установлена',
                      'Kaina pagal užklausą · fiksuota kaina nenustatyta',
                      'Price on request · no fixed fare available')
                  : _rideType == 'Такси'
                      ? 'Такси: ${PdTaxiFare.euros(taxiPrice!)}' +
                          (_requiresCustomQuote
                            ? ' · доп. услуги требуют подтверждения' : '')
                      : _requiresCustomQuote
                      ? pdTr(context,
                          'Расчётная часть: $price € · дополнительные услуги по запросу',
                          'Apskaičiuota dalis: $price € · papildomos paslaugos pagal užklausą',
                          'Estimated portion: €$price · extras priced on request')
                      : pdTr(context,
                          'Предварительная стоимость: $price €',
                          'Preliminari kaina: $price €',
                          'Estimated fare: €$price'),
              key: const Key('passenger-price-preview'),
              style: const TextStyle(
                color: gold, fontWeight: FontWeight.bold, fontSize: 16,
              ),
            ),
            const Text(
              'Дополнительные остановки и изменение маршрута после заказа '
              'согласуются отдельно с диспетчером до выполнения. '
              'Доплата возможна только безналично по согласованию. '
              'Никаких автоматических списаний и изменений '
              'исходного способ оплаты.',
              key: Key('route-adjustment-payment-note'),
              style: TextStyle(fontSize: 12),
            ),
            Text(pdTr(context,
              'Предпросмотр согласованных тарифов. Окончательная цена назначается диспетчером до оплаты.',
              'Suderintų tarifų peržiūra. Galutinę kainą dispečeris patvirtins prieš apmokėjimą.',
              'Fare preview. Dispatcher confirms final price before payment.'),
              style: const TextStyle(fontSize: 12)),
            const SizedBox(height: 12),
            Text(
              pdTr(context, 'Выбрано', 'Pasirinkta', 'Selected') +
                ': ${pdLabel(context, _rideType)} · ${_route.isNotEmpty ? _route : pdLabel(context, 'свой маршрут')} · ' +
                (_payment == 'Карта' ? pdTr(context, 'Карта', 'Kortelė', 'Card') : pdLabel(context, _payment)),
              key: const Key('passenger-summary'),
            ),
            const SizedBox(height: 12),
            if (widget.tripStore != null) ...[
              Text(pdLabel(context, widget.tripStore!.statusLabel),
                  key: const Key('passenger-trip-status')),
              if (widget.tripStore!.trip != null)
                FilledButton.icon(
                  key: const Key('passenger-manage-order'),
                  onPressed: () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => PdPassengerLanguageScope(
                      child: PassengerOrdersDemo(
                        tripStore: widget.tripStore!)))),
                  icon: const Icon(Icons.receipt_long_outlined),
                  label: Text(pdLabel(context, 'Управление заказом · сообщения')),
                ),
              DemoRatingPanel(tripStore: widget.tripStore!),
            ],
            FilledButton(
              key: const Key('passenger-book-disabled'),
              onPressed: _canCreateLocalTrip ? _createLocalTrip : null,
              child: Text(widget.tripStore == null
                  ? pdTr(context, 'Заказать поездку — недоступно в демоверсии',
                      'Užsakyti kelionę — demo versijoje nepasiekiama',
                      'Book ride — unavailable in demo')
                  : pdTr(context, 'Создать тестовую заявку · без сервера',
                      'Sukurti bandomąjį užsakymą · be serverio',
                      'Create demo booking · no server')),
            ),
            const SizedBox(height: 12),
          ],
              );

    return Scaffold(
      drawer: Drawer(
        key: const Key('passenger-navigation-drawer'),
        backgroundColor: const Color(0xFF172033),
        child: SafeArea(child: SingleChildScrollView(child: Column(
          children: [
            const SizedBox(height: 24),
            const CircleAvatar(
              radius: 38,
              backgroundColor: Color(0xFF31405A),
              child: Icon(Icons.person_outline, size: 48, color: gold),
            ),
            const SizedBox(height: 12),
            Text(pdLabel(context, 'Пассажир'), textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            const Divider(height: 32),
            ListTile(
              key: const Key('passenger-drawer-booking'),
              leading: const Icon(Icons.map_outlined),
              title: Text(pdLabel(context, 'Карта и заказ')),
              onTap: () => _openPassengerSection('booking'),
            ),
            ListTile(
              key: const Key('passenger-drawer-routes'),
              leading: const Icon(Icons.route_outlined),
              title: Text(pdLabel(context, 'Популярные направления')),
              onTap: () => _openPassengerSection('routes'),
            ),
            ListTile(
              key: const Key('passenger-drawer-preferences'),
              leading: const Icon(Icons.tune_outlined),
              title: Text(pdLabel(context, 'Личные настройки пассажира')),
              onTap: () => _openPassengerSection('preferences'),
            ),
            ListTile(
              key: const Key('passenger-drawer-payments'),
              leading: const Icon(Icons.credit_card_outlined),
              title: Text(pdLabel(context, 'Способы оплаты')),
              onTap: () => _openPassengerSection('payments'),
            ),
            ListTile(
              key: const Key('passenger-drawer-history'),
              leading: const Icon(Icons.history),
              title: Text(pdTr(context, 'История', 'Istorija', 'History')),
              enabled: widget.tripStore != null,
              onTap: widget.tripStore == null ? null : () {
                Navigator.pop(context);
                _openOrders();
              },
            ),
            ListTile(
              key: const Key('passenger-drawer-profile'),
              leading: const Icon(Icons.account_circle_outlined),
              title: Text(pdTr(context, 'Профиль', 'Profilis', 'Profile')),
              subtitle: Text(pdTr(context, 'После SMS-регистрации',
                'Po SMS registracijos', 'After SMS registration')),
              enabled: false,
            ),
            ListTile(
              leading: const Icon(Icons.card_giftcard_outlined),
              title: Text(pdTr(context, 'Бонусы и промокоды',
                'Premijos ir nuolaidų kodai', 'Rewards and promo codes')),
              enabled: false,
            ),

            ListTile(
              leading: const Icon(Icons.favorite_border),
              title: Text(pdTr(context, 'Избранные адреса',
                'Mėgstami adresai', 'Favorite addresses')),
              enabled: false,
            ),
            ListTile(
              key: const Key('passenger-drawer-language'),
              leading: const Icon(Icons.language),
              title: Text(pdTr(context, 'Язык', 'Kalba', 'Language')),
              trailing: const PdLanguageMenu(),
            ),
            ListTile(
              key: const Key('passenger-permissions-settings'),
              leading: const Icon(Icons.location_on_outlined),
              title: Text(pdTr(context, 'Разрешения приложения',
                'Programėlės leidimai', 'App permissions')),
              onTap: () {
                Navigator.pop(context);
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => const PdPermissionSettingsPage()));
              },
            ),
            ListTile(
              key: const Key('passenger-drawer-info'),
              leading: const Icon(Icons.info_outline),
              title: Text(pdLabel(context, 'Контакты и документы')),
              onTap: () {
                Navigator.pop(context);
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => const CompanyInfoPage()));
              },
            ),
          ],
        ))),
      ),
      appBar: AppBar(
        leadingWidth: Navigator.of(context).canPop() ? 104 : 56,
        leading: Row(children: [
          if (Navigator.of(context).canPop()) const BackButton(),
          Builder(builder: (menuContext) => IconButton(
            key: const Key('passenger-open-drawer'),
            tooltip: pdTr(context, 'Открыть меню', 'Atidaryti meniu', 'Open menu'),
            icon: Container(
              padding: const EdgeInsets.all(5),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                border: Border.all(color: gold),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.menu, color: gold),
            ),
            onPressed: () => Scaffold.of(menuContext).openDrawer(),
          )),
        ]),
        title: Text(pdLabel(context, 'PRIVATE DRIVE · Пассажир')),
        actions: [
          const PdLanguageMenu(),
          if (widget.tripStore != null)
            IconButton(
              key: const Key('passenger-orders-button'),
              tooltip: pdLabel(context, 'Мои заказы'),
              icon: const Icon(Icons.receipt_long_outlined),
              onPressed: _openOrders,
            ),
          IconButton(
            key: const Key('passenger-company-info'),
            tooltip: pdLabel(context, 'Контакты и документы'),
            onPressed: () => Navigator.push(context, MaterialPageRoute(
              builder: (_) => const CompanyInfoPage())),
            icon: const Icon(Icons.info_outline),
          ),
        ],
      ),
      body: SafeArea(
        child: Stack(children: [
          if (widget.enableMapTiles)
            Positioned.fill(child: passengerMap()),
          if (widget.enableMapTiles) DraggableScrollableSheet(
            controller: _passengerSheetController,
            key: const Key('passenger-trip-bottom-sheet'),
            initialChildSize: widget.enableMapTiles ? 0.38 : 1.0,
            minChildSize: widget.enableMapTiles ? 0.20 : 1.0,
            maxChildSize: widget.enableMapTiles ? 0.94 : 1.0,
            snap: widget.enableMapTiles,
            snapSizes: widget.enableMapTiles ? const [0.38, 0.94] : null,
            builder: (context, panelScrollController) => Material(
              color: Theme.of(context).colorScheme.surface.withValues(alpha: 0.95),
              borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
              clipBehavior: Clip.antiAlias,
              elevation: 12,
              child: bookingForm(panelScrollController), // scrolling booking form
            ), // material panel
          ), // draggable panel
          if (!widget.enableMapTiles)
            Positioned.fill(child: bookingForm(null)),
          // Status is driven by the existing order store; no simulated GPS
          // matching, polling or server contact is started here.
          if (widget.tripStore?.status == DemoTripStatus.requested)
            const Positioned(
              top: 74,
              left: 14,
              right: 14,
              child: Center(
                child: IgnorePointer(
                  child: PdPilotAssignmentWaiting(),
                ),
              ),
            ),
        ]), // viewport map stack
      ), // safe area
    );
  }
}
