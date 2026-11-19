import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'remote_sync_client.dart';
import 'message_voice.dart';

/// Opt-in, test-only native client. Credentials are never stored on disk.
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

class RemoteSyncDemo extends StatefulWidget {
  const RemoteSyncDemo({super.key, this.gateway, this.enableMapTiles = true,
    this.pollInterval = const Duration(seconds: 3),
    this.onIncomingMessageVoice});
  final RemoteTripGateway? gateway;
  final bool enableMapTiles;
  final Duration pollInterval;
  final VoidCallback? onIncomingMessageVoice;

  @override
  State<RemoteSyncDemo> createState() => _RemoteSyncDemoState();
}

class _RemoteSyncDemoState extends State<RemoteSyncDemo> {
  final url = TextEditingController();
  final token = TextEditingController();
  final origin = TextEditingController();
  final destination = TextEditingController();
  final chatDraft = TextEditingController();
  final _random = Random.secure();
  final map = MapController();
  RemoteTripGateway? api;
  Timer? timer;
  StreamSubscription<Position>? gps;
  bool owned = false, busy = false, refreshing = false, gpsOn = false;
  String? role, lastTripId;
  String error = '', gpsLabel = 'GPS выключен';
  int seq = 0;
  int chatSeq = 0;
  bool _loadedChatForTrip = false;
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
    if (widget.gateway != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) connect(widget.gateway!, isOwned: false);
      });
    }
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
      timer?.cancel();
      timer = Timer.periodic(widget.pollInterval, (_) => refresh());
    } on Exception catch (e) {
      if (isOwned) candidate.close();
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
    if (role != null) await refresh();
  }

  Future<void> refresh() async {
    final client = api;
    if (client == null || refreshing) return;
    refreshing = true;
    try {
      final response = await client.get('/v1/current');
      final raw = response['trip'];
      if (raw != null && raw is! Map<String, dynamic>) {
        throw const RemoteDemoException('Неверный формат поездки');
      }
      final current = raw as Map<String, dynamic>?;
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
    if (gpsOn) {
      await gps?.cancel();
      gps = null;
      if (mounted) setState(() {
        gpsOn = false; location = null; gpsLabel = 'GPS выключен';
      });
      return;
    }
    if (!widget.enableMapTiles) return;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        if (mounted) setState(() => gpsLabel = 'Включи геолокацию');
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        if (mounted) setState(() => gpsLabel = 'Нет разрешения GPS');
        return;
      }
      if (!mounted) return;
      setState(() { gpsOn = true; gpsLabel = 'Ожидание GPS…'; });
      gps = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high, distanceFilter: 5,
        ),
      ).listen((position) {
        if (!mounted) return;
        final point = LatLng(position.latitude, position.longitude);
        setState(() {
          location = point;
          gpsLabel = 'GPS активен · только на устройстве';
        });
        map.move(point, map.camera.zoom);
      }, onError: (Object _) {
        if (mounted) setState(() => gpsLabel = 'GPS недоступен');
      });
    } on Exception {
      if (mounted) setState(() => gpsLabel = 'GPS недоступен');
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    gps?.cancel();
    if (owned) api?.close();
    url.dispose(); token.dispose(); origin.dispose(); destination.dispose();
    chatDraft.dispose();
    map.dispose();
    super.dispose();
  }

  Widget login() => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE · Тестовый сервер')),
    body: SafeArea(child: ListView(padding: const EdgeInsets.all(20), children: [
      const Text('Подключение только к изолированному тестовому серверу. '
          'Используй HTTPS и временный токен своей роли. '
          'Токен не сохраняется на устройстве.'),
      TextField(key: const Key('remote-server-url'), controller: url,
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

  Widget passengerOrDispatcher() {
    final isPassenger = role == 'passenger';
    return Scaffold(
      appBar: AppBar(title: Text(isPassenger
          ? 'PRIVATE DRIVE · Пассажир · тест'
          : 'PRIVATE DRIVE · Демо-диспетчер')),
      body: SafeArea(child: ListView(
        key: const Key('remote-trip-list'),
        padding: const EdgeInsets.all(18),
        children: [
          const Text('Тестовый сервер · реальные заказы и оплата выключены'),
          const SizedBox(height: 12),
          Text(statusText, key: const Key('remote-trip-status')),
          if (trip != null)
            Text(trip!['origin'].toString() + ' → ' +
                trip!['destination'].toString(),
              key: const Key('remote-trip-route')),
          if (isPassenger && (trip == null || status == 'finished')) ...[
            TextField(key: const Key('remote-from'), controller: origin,
              decoration: const InputDecoration(labelText: 'Откуда')),
            TextField(key: const Key('remote-to'), controller: destination,
              decoration: const InputDecoration(labelText: 'Куда')),
            FilledButton(key: const Key('remote-create'),
              onPressed: busy ? null : () => send('/v1/trips', {
                'from': origin.text, 'to': destination.text, 'payment': 'Карта',
              }),
              child: const Text('Создать тестовую заявку')),
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
    return Scaffold(body: Stack(fit: StackFit.expand, children: [
      if (widget.enableMapTiles)
        FlutterMap(
          key: const Key('remote-pilot-map'), mapController: map,
          options: const MapOptions(
            initialCenter: LatLng(54.6872, 25.2797), initialZoom: 13),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'lt.privatedrive.privateDrive'),
            if (location != null) MarkerLayer(markers: [
              Marker(point: location!, width: 48, height: 48,
                child: const Icon(Icons.navigation, size: 38)),
            ]),
            const RichAttributionWidget(attributions: [
              TextSourceAttribution('© OpenStreetMap contributors'),
            ]),
          ],
        )
      else
        const ColoredBox(key: Key('remote-pilot-map'),
          color: Color(0xFF27332F)),
      SafeArea(child: Stack(children: [
        Positioned(top: 8, right: 8,
          child: Column(children: [
            IconButton.filledTonal(
              key: Key(gpsOn ? 'remote-disable-gps' : 'remote-enable-gps'),
              onPressed: toggleGps,
              icon: Icon(gpsOn ? Icons.location_off : Icons.my_location)),
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
                  if (moving)
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 170),
                      child: SingleChildScrollView(child: chatPanel())),
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
