import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform, kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'remote_sync_client.dart';
import 'pd_trip_voice.dart';
import 'pd_trip_route_editor.dart';
import 'demo_map_tile_provider.dart';
import 'message_voice.dart';

/// Public raster tiles for the isolated map smoke test (no API key).
/// The fallback is used only after visible tile load failures.
String remoteDemoTileTemplate(bool backup) => backup
    ? 'https://tile.openstreetmap.de/{z}/{x}/{y}.png'
    : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

/// Returns the last *other-role* sender in a newly fetched message batch.
/// The last message overall may be an echo of the current user's own reply.
String? newestIncomingChatRole(
    Iterable<Map<String, dynamic>> messages, String? ownRole) {
  String? latest;
  for (final message in messages) {
    final sender = message['role'];
    if (sender is String &&
        ['pilot', 'passenger', 'dispatcher'].contains(sender) &&
        sender != ownRole) {
      latest = sender;
    }
  }
  return latest;
}

/// Opt-in, test-only native client. Credentials are never stored on disk.
class RemoteSyncDemo extends StatefulWidget {
  const RemoteSyncDemo({super.key, this.gateway, this.enableMapTiles = true,
    this.pollInterval = const Duration(seconds: 3),
    this.onIncomingMessageVoice, this.stagingDispatcher = false,
    this.onReturnHome, this.active = true, this.initialFrom = '', this.initialTo = '', this.initialStops = const []});
  final RemoteTripGateway? gateway;
  final bool enableMapTiles;
  final Duration pollInterval;
  final VoidCallback? onIncomingMessageVoice;
  final bool stagingDispatcher;
  final VoidCallback? onReturnHome;
  final bool active;
  /// Pre-populated route from the main passenger booking screen (QA only).
  final String initialFrom, initialTo;
  final List<String> initialStops;

  @override
  State<RemoteSyncDemo> createState() => _RemoteSyncDemoState();
}

class _RemoteSyncDemoState extends State<RemoteSyncDemo>
    with WidgetsBindingObserver {
  static const stagingUrl = 'https://private-drive-dispatcher-staging.onrender.com';
  final url = TextEditingController();
  final token = TextEditingController();
  final origin = TextEditingController();
  final destination = TextEditingController();
  final chatDraft = TextEditingController();
  final _random = Random.secure();
  final map = MapController();
  RemoteTripGateway? api;
  Timer? timer;
  Timer? _offerTicker;
  Map<String, dynamic>? _offer;
  int _offerSeconds = 0;
  StreamSubscription<Position>? gps;
  StreamSubscription<ServiceStatus>? _gpsStatus;
  bool owned = false, busy = false, refreshing = false, gpsOn = false;
  String? role, lastTripId;
  String error = '', gpsLabel = 'GPS выключен';
  String orderError = '';
  List<String> _draftStops = const [];
  int seq = 0;
  int chatSeq = 0;
  bool _loadedChatForTrip = false;
  bool _clearLocation = false;
  bool get _canShareGps => widget.stagingDispatcher &&
      (role == 'pilot' || role == 'passenger');
  bool _refreshRequested = false;
  bool _requestingGpsPermission = false;
  bool _passengerPermissionRequested = false;
  bool _pilotGpsRequested = false;
  AppLifecycleState? _lifecycle;
  bool get _foreground => _lifecycle == null ||
      _lifecycle == AppLifecycleState.resumed ||
      _lifecycle == AppLifecycleState.inactive;
  bool get _androidBackgroundGps =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  bool _closed = false;
  bool _voiceReady = false;
  bool get _autoPassengerGps => widget.stagingDispatcher && role == 'passenger';
  bool get _positionOnline => !_closed && (!_autoPassengerGps || widget.active) &&
      _lifecycle != AppLifecycleState.detached &&
      (_foreground || _androidBackgroundGps);
  bool get _canStartSharedGps => _positionOnline && _foreground;
  bool _sharedPositionSent = false;
  Future<Map<String, dynamic>>? _positionRequest;
  int _gpsGeneration = 0;
  bool _backupTiles = false;
  int _tileErrors = 0;
  int _tileGeneration = 0;
  String? _mapError;
  List<Map<String, dynamic>> chatMessages = [];
  LatLng? location;
  Map<String, dynamic>? trip;
  List<Map<String, dynamic>> events = [];

  String get status => trip?['status'] as String? ?? 'none';
  int get version => trip?['version'] as int? ?? 0;
  bool get paused => trip?['paused'] == 1;
  String get statusText => switch (status) {
    'requested' => 'Заявка создана · ожидает назначения',
    'assigned' => 'Пилот назначен · ожидает выезда',
    'approaching' => paused ? 'Остановка · демо' : 'Пилот едет к пассажиру',
    'underway' => paused ? 'Остановка · демо' : 'Поездка выполняется',
    'finished' => 'Поездка завершена · демо',
    _ => 'Нет тестового заказа',
  };

  @override
  void initState() {
    super.initState();
    _lifecycle = WidgetsBinding.instance.lifecycleState;
    WidgetsBinding.instance.addObserver(this);
    if (widget.stagingDispatcher) url.text = stagingUrl;
    origin.text = widget.initialFrom;
    destination.text = widget.initialTo;
    _draftStops = widget.initialStops;
    if (widget.gateway != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) connect(widget.gateway!, isOwned: false);
      });
    }
  }

  @override
  void didUpdateWidget(covariant RemoteSyncDemo oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active != oldWidget.active) _syncSharedGps();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _lifecycle = state;
    _syncSharedGps();
  }

  void _syncSharedGps() {
    if (!_canShareGps || (!_autoPassengerGps && !_pilotGpsRequested)) return;
    if (!_positionOnline) {
      if (gpsOn) unawaited(_stopGps('Геолокация приостановлена'));
      return;
    }
    if (!_canStartSharedGps) return;
    if (!kIsWeb) {
      try {
        _gpsStatus ??= Geolocator.getServiceStatusStream().listen((status) {
          if (!_positionOnline || (!_autoPassengerGps && !_pilotGpsRequested)) return;
          if (status == ServiceStatus.enabled) {
            unawaited(_startGps());
          } else {
            unawaited(_stopGps('Геолокация устройства выключена'));
          }
        }, onError: (Object _) {
          // The position stream also reports a disabled provider.
        });
      } catch (_) {
        // Some platforms do not support a service status stream.
      }
    }
    unawaited(_startGps());
  }

  Future<void> connectPressed() async {
    try {
      final candidate = RemoteDemoClient(url.text, token.text);
      token.clear();
      await connect(candidate, isOwned: true);
    } on RemoteDemoException catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  Future<void> connect(RemoteTripGateway candidate, {required bool isOwned}) async {
    if (busy) return;
    setState(() { busy = true; error = ''; });
    try {
      final profile = await candidate.get('/v1/me');
      final value = profile['role'];
      if (profile['demo'] != true || value is! String ||
          !['passenger', 'pilot', 'dispatcher'].contains(value)) {
        throw const RemoteDemoException('Требуется изолированный демосервер');
      }
      if (!mounted) return;
      api = candidate;
      owned = isOwned;
      role = value;
      _voiceReady = widget.stagingDispatcher && profile['voice_ready'] == true;
      timer?.cancel();
      timer = Timer.periodic(widget.pollInterval, (_) => refresh());
    } on Exception catch (e) {
      if (isOwned) candidate.close();
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
    if (!mounted) return;
    _syncSharedGps();
    if (role != null) await refresh();
  }

  Future<void> refresh({bool immediately = false}) async {
    final client = api;
    if (client == null || _closed) return;
    if (refreshing) {
      _refreshRequested = _refreshRequested || immediately;
      return;
    }
    refreshing = true;
    try {
      final response = await client.get('/v1/current');
      if (_closed) return;
      final raw = response['trip'];
      if (raw != null && raw is! Map<String, dynamic>) {
        throw const RemoteDemoException('Неверный формат поездки');
      }
      final current = raw as Map<String, dynamic>?;
      final offer = response['offer'];
      if (mounted && role == 'pilot') {
        _setOffer(offer is Map<String, dynamic> ? offer : null);
      }
      if (_canShareGps) {
        final point = gpsOn && _positionOnline
            ? location : null;
        if (point != null || _clearLocation) {
          try {
            if (point != null) _sharedPositionSent = true;
            final request = client.post('/v1/position', {
              'latitude': point?.latitude, 'longitude': point?.longitude,
            });
            _positionRequest = request;
            try {
              await request;
            } finally {
              _positionRequest = null;
            }
            if (_closed) return;
            if (point == null) {
              _clearLocation = false;
              _sharedPositionSent = false;
            }
            if (mounted && gpsOn && point != null) {
              setState(() => gpsLabel = 'GPS передаётся в тестовую диспетчерскую');
            }
          } on RemoteDemoException {
            if (mounted && gpsOn) {
              setState(() => gpsLabel = 'Не удалось передать GPS. Повторяем…');
            }
          }
        }
      }
      final id = current?['id'] as String?;
      if (id != lastTripId) {
        lastTripId = id;
        seq = 0;
        events = [];
        chatSeq = 0;
        chatMessages = [];
        _loadedChatForTrip = false;
      }
      if (id != null) {
        final responseEvents = await client.get('/v1/trips/$id/events?after=$seq');
        final rows = responseEvents['events'];
        if (rows is List) {
          for (final item in rows) {
            if (item is Map<String, dynamic>) {
              events.add(item);
              final n = item['seq'];
              if (n is int && n > seq) seq = n;
            }
          }
          if (events.length > 100) {
            events = events.sublist(events.length - 100);
          }
        }
      }
      if (id != null &&
          ['requested', 'assigned', 'approaching', 'underway', 'finished']
              .contains(current?['status'])) {
        final inbox = await client.get('/v1/trips/$id/messages?after=$chatSeq');
        final rows = inbox['messages'];
        if (rows is! List) {
          throw const RemoteDemoException('Неверный формат чата');
        }
        final newlyReceived = <Map<String, dynamic>>[];
        for (final item in rows) {
          if (item is! Map<String, dynamic> || item['seq'] is! int ||
              item['body'] is! String ||
              !['pilot', 'passenger', 'dispatcher'].contains(item['role'])) {
            throw const RemoteDemoException('Неверное сообщение сервера');
          }
          final n = item['seq'] as int;
          if (n > chatSeq) {
            chatSeq = n;
            chatMessages.add(item);
            newlyReceived.add(item);
          }
        }
        if (chatMessages.length > 100) {
          chatMessages = chatMessages.sublist(chatMessages.length - 100);
        }
        final incomingRole = newestIncomingChatRole(newlyReceived, role);
        if (_loadedChatForTrip && incomingRole != null) {
          if (widget.onIncomingMessageVoice != null) {
            widget.onIncomingMessageVoice!();
          } else {
            unawaited(PdMessageVoice.announce(
              incomingRole == 'dispatcher' ? 'диспетчера' :
              (incomingRole == 'pilot' ? 'пилота' : 'пассажира')));
          }
        }
        _loadedChatForTrip = true;
      }
      if (mounted) setState(() { trip = current; error = ''; });
    } on Exception catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      refreshing = false;
      if (mounted && _refreshRequested) {
        _refreshRequested = false;
        unawaited(refresh());
      }
    }
  }

  void _setOffer(Map<String, dynamic>? offer) {
    final seconds = offer?['seconds_left'];
    final remaining = seconds is int ? seconds : 0;
    final next = remaining > 0 ? offer : null;
    _offerTicker?.cancel();
    _offerTicker = null;
    setState(() {
      _offer = next;
      _offerSeconds = remaining;
    });
    if (next == null) return;
    _offerTicker = Timer.periodic(const Duration(seconds: 1), (ticker) {
      setState(() => _offerSeconds--);
      if (_offerSeconds <= 0) {
        ticker.cancel();
        unawaited(refresh(immediately: true));
      }
    });
  }

  Future<void> _respondToOffer(String decision) async {
    final offer = _offer;
    final client = api;
    if (busy || _offerSeconds <= 0 || offer == null || client == null) return;
    setState(() => busy = true);
    try {
      await client.post('/v1/trips/${offer['trip_id']}/offer', {
        'offer_id': offer['id'], 'decision': decision,
      });
      if (mounted) _setOffer(null);
    } on RemoteDemoException catch (e) {
      if (!mounted) return;
      final message = e.status == 409
          ? 'Предложение заказа уже недоступно.'
          : 'Не удалось отправить ответ. Проверь связь.';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
    } finally {
      if (mounted) {
        setState(() => busy = false);
        unawaited(refresh(immediately: true));
      }
    }
  }

  Future<void> send(String path, Map<String, dynamic> body) async {
    final client = api;
    if (client == null || busy) return;
    setState(() { busy = true; error = ''; });
    try {
      await client.post(path, body);
    } on Exception catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
    await refresh();
  }

  List<String> _routeStops(Map<String, dynamic>? order) =>
      (order?['stops'] as List?)?.whereType<String>().toList() ?? const [];

  String _routeLabel(Map<String, dynamic> order) =>
      [order['origin'], ..._routeStops(order), order['destination']].join(' → ');

  Future<void> _editRoute({required bool draft}) async {
    final order = trip;
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => PdTripRouteEditor(
        origin: draft ? origin.text : order!['origin'] as String,
        destination: draft ? destination.text : order!['destination'] as String,
        stops: draft ? _draftStops : _routeStops(order),
        pickupLocked: !draft && order?['status'] == 'underway',
      ),
    );
    if (!mounted || result == null) return;
    if (draft) {
      setState(() {
        origin.text = result['from'] as String;
        destination.text = result['to'] as String;
        _draftStops = result['stops'] as List<String>;
      });
      return;
    }
    final client = api;
    if (client == null || busy || order == null) return;
    setState(() => busy = true);
    try {
      await client.post('/v1/trips/${order['id']}/route', {
        ...result, 'version': order['version'],
      });
    } on RemoteDemoException catch (error) {
      if (mounted) {
        final message = error.status == 409
            ? 'Заказ изменился. Проверь маршрут и повтори.'
            : 'Не удалось сохранить маршрут. Проверь адреса и связь.';
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
      }
    } finally {
      if (mounted) {
        setState(() => busy = false);
        unawaited(refresh(immediately: true));
      }
    }
  }

  Future<void> createOrder() async {
    final client = api;
    if (client == null || busy) return;
    final from = origin.text.trim();
    final to = destination.text.trim();
    if (from.isEmpty || to.isEmpty || from.toLowerCase() == to.toLowerCase()) {
      setState(() => orderError = 'Укажи разные точки отправления и назначения.');
      return;
    }
    setState(() { busy = true; orderError = ''; });
    try {
      final response = await client.post('/v1/trips', {
        'from': from, 'to': to, 'payment': 'Карта',
        if (_draftStops.isNotEmpty) 'stops': _draftStops,
      });
      final created = response['trip'];
      if (created is! Map<String, dynamic> || created['id'] is! String) {
        throw const RemoteDemoException('Сервер не подтвердил отправку заявки.');
      }
      if (mounted) setState(() => trip = created);
    } on RemoteDemoException catch (failure) {
      if (mounted) setState(() {
        orderError = switch (failure.message) {
          'active_trip_exists' => 'У тебя уже есть активная тестовая заявка.',
          'invalid_route' => 'Проверь адреса отправления и назначения.',
          _ => 'Отправка не подтверждена. Проверь статус заявки перед повтором.',
        };
      });
    } finally {
      if (mounted) setState(() => busy = false);
    }
    await refresh();
  }

  String _newClientId() {
    final bytes = List<int>.generate(16, (_) => _random.nextInt(256));
    return bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
  }

  Future<void> sendChat() async {
    final client = api;
    final id = trip?['id'];
    final message = chatDraft.text.trim();
    if (client == null || id is! String || busy || message.isEmpty ||
        message.length > 500 ||
        !['requested', 'assigned', 'approaching', 'underway'].contains(status)) return;
    setState(() { busy = true; error = ''; });
    try {
      await client.post('/v1/trips/$id/messages',
        {'client_id': _newClientId(), 'text': message});
      chatDraft.clear();
    } on Exception catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
    await refresh();
  }

  Widget chatPanel() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    mainAxisSize: MainAxisSize.min,
    children: [
      const Text('Сообщения поездки · тестовый сервер'),
      if (_voiceReady && _androidBackgroundGps && widget.active &&
          (role == 'pilot' || role == 'passenger') &&
          ['assigned', 'approaching', 'underway'].contains(status) &&
          trip?['pilot'] != null)
        PdTripVoice(
          key: ValueKey(trip!['id']),
          gateway: api!,
          tripId: trip!['id'] as String,
          role: role!,
        ),
      for (final item in chatMessages)
        Text('${switch (item['role']) { 'pilot' => 'Пилот', 'dispatcher' => 'Диспетчер', _ => 'Пассажир' }}: ${item['body']}',
          key: Key('remote-chat-message-${item['seq']}')),
      if (['requested', 'assigned', 'approaching', 'underway'].contains(status))
      Row(children: [
        Expanded(child: TextField(
          key: const Key('remote-chat-input'),
          controller: chatDraft,
          maxLength: 500,
          decoration: const InputDecoration(
            hintText: 'Сообщение по заказу', counterText: ''),
        )),
        IconButton(
          key: const Key('remote-chat-send'),
          icon: const Icon(Icons.send),
          onPressed: busy ? null : sendChat,
        ),
      ]),
      const Text('Только изолированный сервер. Без SMS и уведомлений ОС.',
        style: TextStyle(fontSize: 11)),
    ],
  );

  Future<void> toggleGps() async {
    if (_requestingGpsPermission) return;
    if (_canShareGps && role == 'pilot') {
      _pilotGpsRequested = !_pilotGpsRequested;
      if (!_pilotGpsRequested) {
        await _stopGps('GPS выключен');
      } else {
        _syncSharedGps();
      }
      return;
    }
    if (gpsOn) {
      await _stopGps('GPS выключен');
      return;
    }
    await _startGps();
  }

  Future<void> _startGps() async {
    if (!mounted || gpsOn || _requestingGpsPermission ||
        (_canShareGps && !_canStartSharedGps)) return;
    _requestingGpsPermission = true;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        if (mounted) setState(() => gpsLabel = 'Включи геолокацию');
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied &&
          (!_autoPassengerGps || !_passengerPermissionRequested) &&
          (!_canShareGps || _canStartSharedGps) && mounted) {
        if (_autoPassengerGps) _passengerPermissionRequested = true;
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        if (mounted) setState(() => gpsLabel = 'Нет разрешения GPS');
        return;
      }
      if (!mounted || (_canShareGps && !_canStartSharedGps)) return;
      final generation = ++_gpsGeneration;
      setState(() { gpsOn = true; gpsLabel = 'Ожидание GPS…'; });
      void updatePosition(Position position) {
        if (!mounted || !gpsOn || _gpsGeneration != generation) return;
        final point = LatLng(position.latitude, position.longitude);
        setState(() {
          location = point;
          gpsLabel = _canShareGps
              ? 'Координаты получены · отправляем…'
              : 'GPS активен · только на устройстве';
        });
        if (widget.enableMapTiles) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted || !_foreground || !gpsOn || _gpsGeneration != generation ||
                location != point) return;
            map.move(point, map.camera.zoom);
          });
        }
        if (_canShareGps) unawaited(refresh(immediately: true));
      }
      final settings = _canShareGps && _androidBackgroundGps
          ? AndroidSettings(
              accuracy: LocationAccuracy.high,
              distanceFilter: 5,
              intervalDuration: const Duration(seconds: 3),
              foregroundNotificationConfig: const ForegroundNotificationConfig(
                notificationTitle: 'PRIVATE DRIVE · Геолокация',
                notificationText: 'Тестовый диспетчер видит твоё местоположение, пока ты онлайн.',
                notificationChannelName: 'Геолокация поездки',
                enableWakeLock: true,
                setOngoing: true,
              ),
            )
          : const LocationSettings(
              accuracy: LocationAccuracy.high,
              distanceFilter: 5,
            );
      gps = Geolocator.getPositionStream(locationSettings: settings)
          .listen(updatePosition, onError: (Object _) {
        if (mounted && _gpsGeneration == generation) {
          unawaited(_stopGps('GPS недоступен'));
        }
      });
      unawaited(_getInitialFix(generation, updatePosition));
    } catch (_) {
      if (mounted) await _stopGps('GPS недоступен');
    } finally {
      _requestingGpsPermission = false;
    }
  }

  Future<void> _stopGps(String label) async {
    _gpsGeneration++;
    final stopped = gps;
    gps = null;
    _clearLocation = _canShareGps && _sharedPositionSent;
    setState(() {
      gpsOn = false;
      location = null;
      gpsLabel = label;
    });
    if (_clearLocation) unawaited(refresh(immediately: true));
    await stopped?.cancel();
  }

  Future<void> _getInitialFix(int generation, ValueChanged<Position> updatePosition) async {
    try {
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15)));
      if (mounted && gpsOn && _gpsGeneration == generation && location == null) {
        updatePosition(position);
      }
    } on Exception {
      if (mounted && gpsOn && _gpsGeneration == generation && location == null) {
        setState(() => gpsLabel = 'Нет координат. Проверь геолокацию.');
      }
    }
  }

  Future<void> _closeSharedGpsConnection(RemoteTripGateway client,
      Future<Map<String, dynamic>>? pending) async {
    try {
      try {
        await pending;
      } catch (_) {
        // A lost response does not mean the previous position did not arrive.
      }
      await client.post('/v1/position', {'latitude': null, 'longitude': null});
    } catch (_) {
      // The dispatcher drops stale positions when the client cannot clear them.
    } finally {
      if (owned) client.close();
    }
  }

  @override
  void dispose() {
    _closed = true;
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    _offerTicker?.cancel();
    gps?.cancel();
    _gpsStatus?.cancel();
    final client = api;
    if (_canShareGps && _sharedPositionSent && client != null) {
      unawaited(_closeSharedGpsConnection(client, _positionRequest));
    } else if (owned) {
      client?.close();
    }
    url.dispose(); token.dispose(); origin.dispose(); destination.dispose();
    chatDraft.dispose();
    map.dispose();
    super.dispose();
  }

  Widget login() => Scaffold(
    appBar: AppBar(
      title: const Text('PRIVATE DRIVE · Тестовый сервер'),
      leading: widget.onReturnHome == null ? null : BackButton(onPressed: widget.onReturnHome),
    ),
    body: SafeArea(child: ListView(padding: const EdgeInsets.all(20), children: [
      const Text('Подключение только к изолированному тестовому серверу. '
          'Используй HTTPS и временный токен своей роли. '
          'Токен не сохраняется на устройстве.'),
      if (widget.stagingDispatcher)
        const Text('В режиме пассажира разрешённая геолокация автоматически '
            'видна тестовому диспетчеру, пока ты онлайн, в том числе при свёрнутом приложении на Android.'),
      TextField(key: const Key('remote-server-url'), controller: url,
        readOnly: widget.stagingDispatcher,
        decoration: const InputDecoration(labelText: 'HTTPS-адрес')),
      TextField(key: const Key('remote-token'), controller: token,
        obscureText: true,
        decoration: const InputDecoration(labelText: 'Временный токен')),
      FilledButton(key: const Key('remote-connect'),
        onPressed: busy ? null : connectPressed,
        child: const Text('Подключиться')),
      if (error.isNotEmpty) Text(error, key: const Key('remote-error')),
    ])),
  );

  /// Same public, keyless raster source on Safari and Android.
  /// A tile failure is not a GPS permission failure: report it separately.
  Widget _sharedMap() => Stack(children: [
    FlutterMap(
      key: const Key('remote-shared-map'),
      mapController: map,
      options: const MapOptions(
        initialCenter: LatLng(54.6872, 25.2797),
        initialZoom: 13,
      ),
      children: [
        TileLayer(
          key: ValueKey('remote-map-tiles-$_tileGeneration'),
          tileProvider: demoTileProvider(),
          urlTemplate: remoteDemoTileTemplate(_backupTiles),
          userAgentPackageName: 'lt.privatedrive.privateDrive.demo',
          errorTileCallback: (tile, error, stackTrace) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (!mounted) return;
              setState(() {
                _tileErrors++;
                if (_tileErrors >= 3 && !_backupTiles) {
                  _backupTiles = true;
                  _tileErrors = 0;
                  _tileGeneration++;
                  _mapError = null;
                } else if (_tileErrors >= 3) {
                  _mapError = 'Тайлы карты недоступны. Проверь HTTPS и CORS в Safari.';
                }
              });
            });
          },
        ),
        if (location != null) MarkerLayer(markers: [
          Marker(point: location!, width: 48, height: 48,
            child: const Icon(Icons.navigation, size: 38)),
        ]),
        const RichAttributionWidget(attributions: [
          TextSourceAttribution('© OpenStreetMap contributors'),
        ]),
      ],
    ),
    if (_mapError != null)
      Positioned(top: 8, left: 8, right: 8,
        child: Card(child: Padding(
          padding: const EdgeInsets.all(8),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_mapError!, key: const Key('remote-map-error')),
            TextButton(
              key: const Key('remote-map-retry'),
              onPressed: () => setState(() {
                _mapError = null;
                _tileErrors = 0;
                _backupTiles = false;
                _tileGeneration++;
              }),
              child: const Text('Повторить загрузку карты'),
            ),
          ]),
        )),
      ),
  ]);

  Widget passengerOrDispatcher() {
    final isPassenger = role == 'passenger';
    return Scaffold(
      appBar: AppBar(title: Text(isPassenger
          ? 'PRIVATE DRIVE · Пассажир · тест'
          : 'PRIVATE DRIVE · Демо-диспетчер'),
        leading: widget.onReturnHome == null ? null : BackButton(onPressed: widget.onReturnHome)),
      body: SafeArea(child: ListView(
        key: const Key('remote-trip-list'),
        padding: const EdgeInsets.all(18),
        children: [
          const Text('Тестовый сервер · реальные заказы и оплата выключены'),
          const SizedBox(height: 12),
          Text(statusText, key: const Key('remote-trip-status')),
          if (isPassenger && widget.enableMapTiles)
            SizedBox(height: 240, child: _sharedMap()),
          if (_autoPassengerGps)
            Text(gpsLabel, key: const Key('remote-passenger-gps-status')),
          if (trip != null)
            Text(_routeLabel(trip!), key: const Key('remote-trip-route')),
          if (isPassenger && widget.stagingDispatcher &&
              ['requested','assigned','approaching','underway'].contains(status))
            OutlinedButton.icon(
              key: const Key('remote-edit-route'),
              onPressed: busy ? null : () => _editRoute(draft: false),
              icon: const Icon(Icons.route_outlined),
              label: const Text('Изменить маршрут'),
            ),
          if (isPassenger && (trip == null || status == 'finished')) ...[
            TextField(key: const Key('remote-from'), controller: origin,
              maxLength: 200,
              decoration: const InputDecoration(labelText: 'Откуда')),
            TextField(key: const Key('remote-to'), controller: destination,
              maxLength: 200,
              decoration: const InputDecoration(labelText: 'Куда')),
            if (widget.stagingDispatcher)
              OutlinedButton.icon(
                key: const Key('remote-edit-draft-route'),
                onPressed: busy ? null : () => _editRoute(draft: true),
                icon: const Icon(Icons.add_location_alt_outlined),
                label: Text(_draftStops.isEmpty ? 'Добавить остановки'
                    : 'Остановки: ${_draftStops.length}'),
              ),
            FilledButton(key: const Key('remote-create'),
              onPressed: busy ? null : createOrder,
              child: Text(busy ? 'Отправляем заявку…' : 'Создать тестовую заявку')),
            if (orderError.isNotEmpty)
              Text(orderError, key: const Key('remote-order-error')),
          ],
          if (!isPassenger && status == 'requested')
            FilledButton(key: const Key('remote-assign'),
              onPressed: busy ? null : () => send(
                '/v1/trips/' + trip!['id'].toString() + '/assign',
                {'pilot': 'pilot_test', 'version': version}),
              child: const Text('Назначить тестового пилота')),
          if (trip != null &&
              ['requested','assigned','approaching','underway','finished'].contains(status))
            chatPanel(),
          OutlinedButton(key: const Key('remote-refresh'),
            onPressed: refresh, child: const Text('Обновить статус')),
          if (error.isNotEmpty)
            Text(error, key: const Key('remote-error')),
          for (final item in events)
            Text(item['version'].toString() + ': ' + item['event'].toString()),
        ],
      )),
    );
  }

  Widget pilot() {
    final moving = ['assigned', 'approaching', 'underway'].contains(status);
    final pauseAllowed = ['approaching', 'underway'].contains(status);
    final actionLabel = switch (status) {
      'assigned' => 'К пассажиру',
      'approaching' => 'В путь',
      'underway' => 'Завершить',
      _ => 'Нет назначенной поездки',
    };
    final gpsRequested = _canShareGps ? _pilotGpsRequested : gpsOn;
    return Scaffold(body: Stack(fit: StackFit.expand, children: [
      if (widget.enableMapTiles)
        KeyedSubtree(key: const Key('remote-pilot-map'), child: _sharedMap())
      else
        const ColoredBox(key: Key('remote-pilot-map'),
          color: Color(0xFF27332F)),
      SafeArea(child: Stack(children: [
        if (widget.onReturnHome != null)
          Positioned(top: 8, left: 8,
            child: IconButton.filledTonal(
              tooltip: 'На главный экран',
              onPressed: widget.onReturnHome,
              icon: const Icon(Icons.arrow_back),
            )),
        Positioned(top: 8, right: 8,
          child: Column(children: [
            FilledButton.tonalIcon(
              key: Key(gpsRequested ? 'remote-disable-gps' : 'remote-enable-gps'),
              onPressed: toggleGps,
              label: Text(gpsRequested ? 'Выключить GPS' : _canShareGps
                  ? 'Поделиться GPS' : 'Включить GPS'),
              icon: Icon(gpsRequested ? Icons.location_off : Icons.my_location)),
            Text(gpsLabel, style: const TextStyle(fontSize: 11)),
          ])),
        Align(alignment: Alignment.bottomCenter,
          child: Padding(padding: const EdgeInsets.all(14),
            child: Card(color: const Color(0xE9111111),
              child: Padding(padding: const EdgeInsets.all(12),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(statusText, key: const Key('remote-trip-status')),
                  if (error.isNotEmpty)
                    Text(error, key: const Key('remote-error')),
                  if (_offer case final Map<String, dynamic> offer)
                    Column(key: const Key('remote-pilot-offer'), children: [
                      Text('Новый заказ · $_offerSeconds с'),
                      Text('${offer['origin']} → ${offer['destination']}'),
                      Row(children: [
                        Expanded(child: OutlinedButton(
                          key: const Key('remote-offer-decline'),
                          onPressed: busy || _offerSeconds <= 0
                              ? null : () => _respondToOffer('decline'),
                          child: const Text('Отклонить'),
                        )),
                        const SizedBox(width: 8),
                        Expanded(child: FilledButton(
                          key: const Key('remote-offer-accept'),
                          onPressed: busy || _offerSeconds <= 0
                              ? null : () => _respondToOffer('accept'),
                          child: const Text('Принять'),
                        )),
                      ]),
                    ]),
                  if (moving)
                    Text('Оплата: ${trip!['payment'] ?? 'способ не указан'} · без списания',
                      key: const Key('remote-pilot-payment-status')),
                  if (moving)
                    Text(_routeLabel(trip!), key: const Key('remote-pilot-route'),
                      maxLines: 3, overflow: TextOverflow.ellipsis),
                  if (moving)
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 170),
                      child: SingleChildScrollView(child: chatPanel())),
                  if (_offer == null)
                  Row(children: [
                    Expanded(child: FilledButton(
                      key: const Key('remote-pilot-next'),
                      onPressed: moving && !paused && !busy
                          ? () => send('/v1/trips/' +
                              trip!['id'].toString() + '/action',
                              {'action': 'advance', 'version': version})
                          : null,
                      child: Text(actionLabel))),
                    const SizedBox(width: 8),
                    OutlinedButton(key: const Key('remote-pilot-pause'),
                      onPressed: pauseAllowed && !busy
                          ? () => send('/v1/trips/' +
                              trip!['id'].toString() + '/action',
                              {'action': paused ? 'resume' : 'pause',
                               'version': version})
                          : null,
                      child: Text(paused ? 'Продолжить' : 'Остановка')),
                  ]),
                ])))),
        ),
      ])),
    ]));
  }

  @override
  Widget build(BuildContext context) {
    if (role == null) return login();
    if (role == 'pilot') return pilot();
    return passengerOrDispatcher();
  }
}
