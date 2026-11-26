import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'pd_http_api.dart';
import 'qa_pilot_gps.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb, kDebugMode, TargetPlatform;

class PilotAssignedOrder {
  const PilotAssignedOrder({
    required this.orderId,
    required this.origin,
    required this.destination,
    required this.date,
    required this.time,
    required this.status,
    this.waitingSeconds = 0,
    this.waitingActive = false,
    this.stopChargeCents = 0,
  });

  final String orderId;
  final String origin;
  final String destination;
  final String date;
  final String time;
  final String status;
  final int waitingSeconds;
  final bool waitingActive;
  final int stopChargeCents;

  static final _uuid = RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
  );

  static PilotAssignedOrder parse(Object? data) {
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Invalid assigned order');
    }
    String value(String name, {int maxLength = 200}) {
      final field = data[name];
      if (field is! String || field.isEmpty || field.length > maxLength) {
        throw const FormatException('Invalid assigned order field');
      }
      return field;
    }

    final id = value('order_id', maxLength: 36);
    final status = value('status', maxLength: 16);
    if (!_uuid.hasMatch(id) ||
        !(const {'assigned', 'approaching', 'arrived', 'underway'}.contains(status))) {
      throw const FormatException('Unknown assigned order');
    }
    return PilotAssignedOrder(
      orderId: id,
      origin: value('from'),
      destination: value('to'),
      date: value('trip_date', maxLength: 10),
      time: value('trip_time', maxLength: 5),
      status: status,
      waitingSeconds: data['waiting_seconds'] is int &&
          (data['waiting_seconds'] as int) >= 0
          ? data['waiting_seconds'] as int : 0,
      waitingActive: data['waiting_active'] == true,
      stopChargeCents: data['stop_charge_cents'] is int ? data['stop_charge_cents'] as int : 0,
    );
  }

  String get statusLabel => switch (status) {
    'assigned' => 'Назначен',
    'approaching' => 'Пилот едет к пассажиру',
    'arrived' => 'На месте',
    'underway' => 'В поездке',
    _ => 'Статус неизвестен',
  };
}

/// Read-only staging transport. The existing native Bearer remains in memory
/// and is never forwarded by redirects, stored here, or put in URLs.
class NativePilotOrdersApi {
  const NativePilotOrdersApi({
    required this.baseUrl,
    required this.token,
    http.Client? client,
  }) : _client = client;

  final String baseUrl;
  final String token;
  final http.Client? _client;
  static const stage = 'https://private-drive-drbd.onrender.com';
  static const _timeout = Duration(seconds: 7);

  static const qaGpsEnabled = bool.fromEnvironment('PD_QA28_GPS') &&
      bool.fromEnvironment('PD_INTERNAL_QA');

  // QA29 is a separate debug-only APK. It can never send a real session
  // to plaintext HTTP, or reach the existing staging/production service.
  static const qaIosGps = bool.fromEnvironment('PD_QA_IOS_GPS') && qaGpsEnabled;
  static const qaIosBase = 'https://qa.invalid';
  bool get _qaIosAllowed => qaIosGps && baseUrl == qaIosBase &&
      token.startsWith('qa-ios-synthetic-') && token.length >= 40 &&
      _client != null;
  static const qa29Loopback = bool.fromEnvironment('PD_QA29_LOOPBACK') &&
      qaGpsEnabled && kDebugMode;
  static const qa29Base = 'http://127.0.0.1:18729';
  bool get _qa29Allowed => qa29Loopback && baseUrl == qa29Base &&
      token.startsWith('qa29-synthetic-') && token.length >= 40;
  static const _configuredBase = String.fromEnvironment('PD_NATIVE_AUTH_API_URL');

  bool get _allowed {
    if (qaIosGps) return _qaIosAllowed;
    if (qa29Loopback) return _qa29Allowed;
    return baseUrl == stage ||
        (_configuredBase.isNotEmpty && baseUrl == _configuredBase);
  }

  Uri _endpoint(String path) {
    if (!_allowed) throw const FormatException('Unapproved pilot API');
    if (_qa29Allowed) return Uri.parse(qa29Base).resolve(path);
    return PdHttpApi.secureUri(baseUrl, path);
  }

  Future<void> publishGps(String orderId, QaGpsFix? fix, int capturedAt) async {
    if (!qaGpsEnabled || !_allowed ||
        !PilotAssignedOrder._uuid.hasMatch(orderId)) {
      throw const FormatException('GPS requires isolated QA and assigned order');
    }
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    if (capturedAt <= 0 || (fix != null &&
        (fix.capturedAt != capturedAt || !fix.latitude.isFinite ||
         !fix.longitude.isFinite || fix.latitude.abs() > 90 ||
         fix.longitude.abs() > 180))) {
      throw const FormatException('Invalid GPS fix');
    }
    final transport = _client ?? http.Client();
    try {
      final request = http.Request('POST', _endpoint('/native-pilot-orders/$orderId/gps'))
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $token'
        ..headers['Content-Type'] = 'application/json'
        ..body = jsonEncode({
          'enabled': fix != null, 'captured_at': capturedAt,
          if (fix != null) 'latitude': fix.latitude,
          if (fix != null) 'longitude': fix.longitude,
        });
      final response = await transport.send(request).timeout(_timeout);
      if (response.statusCode != 200) {
        throw PdHttpStatusException(response.statusCode);
      }
      final bytes = <int>[];
      await response.stream.timeout(_timeout).forEach((chunk) {
        if (bytes.length + chunk.length > 1024) {
          throw const FormatException('GPS response too large');
        }
        bytes.addAll(chunk);
      }).timeout(_timeout);
      final data = jsonDecode(utf8.decode(bytes));
      if (data is! Map<String, dynamic> || data['available'] != (fix != null)) {
        throw const FormatException('GPS acknowledgement missing');
      }
    } finally {
      if (_client == null) transport.close();
    }
  }

  Future<bool> availability([bool? desiredOnline]) async {
    if (!_allowed) {
      throw const FormatException('Pilot availability requires staging');
    }
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    final client = _client ?? http.Client();
    try {
      final request = http.Request(
        desiredOnline == null ? 'GET' : 'PATCH',
        _endpoint('/native-pilot-availability'))
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $token'
        ..headers['Accept'] = 'application/json';
      if (desiredOnline != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = jsonEncode({'online': desiredOnline});
      }
      final response = await client.send(request).timeout(_timeout);
      if (response.statusCode != 200) {
        throw PdHttpStatusException(response.statusCode);
      }
      final bytes = <int>[];
      await response.stream.timeout(_timeout).forEach((chunk) {
        if (bytes.length + chunk.length > 2048) {
          throw const FormatException('Availability response too large');
        }
        bytes.addAll(chunk);
      }).timeout(_timeout);
      final data = jsonDecode(utf8.decode(bytes));
      if (data is! Map<String, dynamic> || data['payment_mode'] != 'disabled' ||
          data['online'] is! bool ||
          (desiredOnline != null && data['online'] != desiredOnline)) {
        throw const FormatException('Unconfirmed pilot availability');
      }
      return data['online'] as bool;
    } finally {
      if (_client == null) client.close();
    }
  }

  Future<Map<String, dynamic>> action(String orderId, String action) async {
    if (!_allowed || _qa29Allowed) {
      throw const FormatException('Unapproved pilot trip API');
    }
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    if (!PilotAssignedOrder._uuid.hasMatch(orderId) ||
        !const {'approach', 'arrive', 'start', 'finish', 'stop_start', 'stop_end'}.contains(action)) {
      throw const FormatException('Invalid trip action');
    }
    final client = _client ?? http.Client();
    try {
      final request = http.Request(
        'PATCH', _endpoint('/native-pilot-orders'))
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $token'
        ..headers['Content-Type'] = 'application/json'
        ..body = jsonEncode({'order_id': orderId, 'action': action});
      final response = await client.send(request).timeout(_timeout);
      if (response.statusCode != 200) {
        throw PdHttpStatusException(response.statusCode);
      }
      final bytes = <int>[];
      await response.stream.timeout(_timeout).forEach((chunk) {
        if (bytes.length + chunk.length > 8192) {
          throw const FormatException('Trip response too large');
        }
        bytes.addAll(chunk);
      }).timeout(_timeout);
      final data = jsonDecode(utf8.decode(bytes));
      if (data is! Map<String, dynamic> ||
          data['order_id'] != orderId || data['payment_mode'] != 'disabled' ||
          !const {'approaching', 'arrived', 'underway', 'finished'}.contains(data['status'])) {
        throw const FormatException('Invalid trip acknowledgement');
      }
      return data;
    } finally {
      if (_client == null) client.close();
    }
  }

  Future<List<PilotAssignedOrder>> load() async {
    final endpoint = _endpoint('/native-pilot-orders');
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    final request = http.Request(
      'GET', endpoint,
    )
      ..followRedirects = false
      ..headers['Authorization'] = 'Bearer $token'
      ..headers['Accept'] = 'application/json';
    final client = _client ?? http.Client();
    try {
      final response = await client.send(request).timeout(_timeout);
      if (response.statusCode != 200) {
        throw PdHttpStatusException(response.statusCode);
      }
      final bytes = <int>[];
      await response.stream.timeout(_timeout).forEach((chunk) {
        if (bytes.length + chunk.length > 524288) {
          throw const FormatException('Assigned order response too large');
        }
        bytes.addAll(chunk);
      }).timeout(_timeout);
      final data = jsonDecode(utf8.decode(bytes));
      if (data is! Map<String, dynamic> || data['payment_mode'] != 'disabled') {
        throw const FormatException('Unsafe assigned order response');
      }
      final rows = data['orders'];
      if (rows is! List || rows.length > 100) {
        throw const FormatException('Invalid assigned order list');
      }
      return List<PilotAssignedOrder>.unmodifiable(rows.map(PilotAssignedOrder.parse));
    } finally {
      if (_client == null) client.close();
    }
  }
}

/// The connected shift control never uses a local substitute for server state.
/// It starts unknown until a validated server read has completed.
class PilotServerAvailabilityButton extends StatefulWidget {
  const PilotServerAvailabilityButton({super.key, required this.api});
  final NativePilotOrdersApi api;

  @override
  State<PilotServerAvailabilityButton> createState() =>
      _PilotServerAvailabilityButtonState();
}

class _PilotServerAvailabilityButtonState
    extends State<PilotServerAvailabilityButton> with WidgetsBindingObserver {
  bool? _online;
  bool _busy = false;
  String? _error;
  int _generation = 0;
  bool _foreground = true;
  Timer? _heartbeatTimer;

  Future<void> _heartbeat() async {
    if (!mounted || !_foreground || _online != true || _busy) return;
    final generation = ++_generation;
    setState(() => _busy = true);
    try {
      final confirmed = await widget.api.availability(true);
      if (mounted && generation == _generation) {
        setState(() => _online = confirmed);
      }
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(() {
          _online = null;
          _error = 'Связь потеряна. Статус линии не подтверждён.';
        });
      }
    } finally {
      if (mounted && generation == _generation) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final lifecycle = WidgetsBinding.instance.lifecycleState;
    _foreground = lifecycle == null || lifecycle == AppLifecycleState.resumed;
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 45), (_) {
      if (_foreground) _heartbeat();
    });
    _read();
  }

  @override
  void didUpdateWidget(PilotServerAvailabilityButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api.baseUrl != widget.api.baseUrl ||
        oldWidget.api.token != widget.api.token) {
      _generation++;
      _online = null;
      _error = null;
      _busy = false;
      _read();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _foreground = true;
      _read();
    } else if (mounted) {
      _foreground = false;
      _generation++;
      setState(() => _online = null);
    }
  }

  Future<void> _read() async {
    final generation = ++_generation;
    if (mounted) setState(() { _busy = true; _error = null; });
    try {
      final online = await widget.api.availability();
      if (mounted && generation == _generation) setState(() => _online = online);
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(() { _online = null; _error = 'Не удалось получить статус линии'; });
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _toggle() async {
    final prior = _online;
    if (prior == null || _busy) return;
    final generation = ++_generation;
    setState(() { _busy = true; _error = null; });
    try {
      final confirmed = await widget.api.availability(!prior);
      if (mounted && generation == _generation) setState(() => _online = confirmed);
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(() {
          _online = null;
          _error = 'Сервер не подтвердил смену статуса. Проверь статус снова.';
        });
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _generation++;
    _heartbeatTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(children: [
    Text(
      _online == true ? 'НА ЛИНИИ' :
          _online == false ? 'НЕ НА ЛИНИИ' : 'СТАТУС НЕИЗВЕСТЕН',
      key: const Key('pilot-server-line-status'),
      style: TextStyle(fontWeight: FontWeight.w800,
        color: _online == true
            ? const Color(0xFF34E88A) : const Color(0xFFFC4654)),
    ),
    const SizedBox(height: 8),
    FilledButton.icon(
      key: const Key('pilot-server-line-toggle'),
      onPressed: _busy || _online == null ? null : _toggle,
      icon: Icon(_online == true ? Icons.power_off : Icons.power_settings_new),
      label: Text(_busy ? 'Проверка…' :
          _online == true ? 'УЙТИ С ЛИНИИ' : 'ВЫЙТИ НА ЛИНИЮ'),
    ),
    if (_error != null) ...[
      Text(_error!, key: const Key('pilot-server-line-error')),
      TextButton(onPressed: _busy ? null : _read,
        child: const Text('Повторить проверку')),
    ],
  ]);
}

/// Server-truth projection within the existing pilot cabin, not a trip demo.
/// Reads only when mounted in the foreground; never invokes mutable actions.
class PilotAssignedOrdersPanel extends StatefulWidget {
  const PilotAssignedOrdersPanel({
    super.key, required this.api, this.visible = true,
  });

  final NativePilotOrdersApi api;
  final bool visible;

  @override
  State<PilotAssignedOrdersPanel> createState() =>
      _PilotAssignedOrdersPanelState();
}

class _PilotAssignedOrdersPanelState extends State<PilotAssignedOrdersPanel>
    with WidgetsBindingObserver {
  List<PilotAssignedOrder>? _orders;
  Timer? _refreshTimer;
  String? _error;
  bool _loading = false;
  bool _foreground = true;
  int _generation = 0;
  String? _actingOrderId;
  QaPilotGpsPublisher? _gpsPublisher;
  bool _gpsStarting = false;

  Future<void> _toggleGps(PilotAssignedOrder order) async {
    if (_gpsStarting || !_foreground || !widget.visible) return;
    final prior = _gpsPublisher;
    if (prior != null && prior.orderId == order.orderId) {
      await prior.stop();
      return;
    }
    if (prior?.orderId != null || prior?.busy == true) return;
    final api = widget.api;
    setState(() { _gpsStarting = true; _error = null; });
    try {
      if (defaultTargetPlatform == TargetPlatform.iOS) {
        final consent = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Передача GPS назначенной поездки'),
            content: const Text('Координаты будут передаваться диспетчеру, в том числе при блокировке экрана. Передачу можно остановить в любой момент. После завершения поездки она прекращается.'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
              FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Разрешить GPS')),
            ],
          ),
        );
        if (consent != true || !mounted || !_foreground || !widget.visible ||
            !identical(api, widget.api)) return;
      }
      if (!await qaGpsPermission() || !mounted || !_foreground ||
          !widget.visible || !identical(api, widget.api)) return;
      final publisher = QaPilotGpsPublisher(
        send: api.publishGps,
        isAssigned: (id) async => (await api.load()).any((row) => row.orderId == id),
        positions: defaultTargetPlatform == TargetPlatform.iOS ? qaIosPositions : qaAndroidPositions,
        canStart: () => mounted && _foreground && widget.visible && identical(api, widget.api),
        onStopped: () { if (mounted) setState(() {}); },
      );
      _gpsPublisher = publisher;
      final started = await publisher.start(order.orderId);
      if (!mounted || !identical(api, widget.api)) {
        await publisher.stop();
        return;
      }
      if (!started) setState(() => _error = 'GPS: назначение не подтверждено.');
    } catch (_) {
      if (mounted) setState(() => _error = 'GPS недоступен.');
    } finally {
      if (mounted) setState(() => _gpsStarting = false);
    }
  }

  Future<void> _perform(PilotAssignedOrder order, String action) async {
    if (_actingOrderId != null || _loading) return;
    setState(() { _actingOrderId = order.orderId; _error = null; });
    try {
      if (action == 'finish' && _gpsPublisher?.orderId == order.orderId) {
        await _gpsPublisher?.stop();
      }
      await widget.api.action(order.orderId, action);
      if (mounted) {
        setState(() => _actingOrderId = null);
        await _refresh();
      }
    } catch (_) {
      if (mounted) setState(() {
        _actingOrderId = null;
        _error = 'Сервер не подтвердил действие. Статус заказа не изменён.';
      });
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final lifecycle = WidgetsBinding.instance.lifecycleState;
    _foreground = lifecycle == null || lifecycle == AppLifecycleState.resumed;
    unawaited(_refresh());
  }

  @override
  void didUpdateWidget(PilotAssignedOrdersPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api.baseUrl != widget.api.baseUrl ||
        oldWidget.api.token != widget.api.token ||
        oldWidget.visible != widget.visible) {
      if (oldWidget.api.baseUrl != widget.api.baseUrl ||
          oldWidget.api.token != widget.api.token ||
          (NativePilotOrdersApi.qaIosGps && !widget.visible)) {
        final old = _gpsPublisher;
        _gpsPublisher = null;
        if (old != null) unawaited(old.stop());
      }
      _forget();
      if (widget.visible) unawaited(_refresh());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (_foreground) {
      unawaited(_refresh());
    } else {
      setState(_forget);
    }
  }

  void _forget() {
    _generation++;
    _refreshTimer?.cancel();
    _orders = null;
    _error = null;
    _loading = false;
  }

  Future<void> _refresh() async {
    if (!widget.visible || !_foreground || _loading) return;
    _refreshTimer?.cancel();
    final generation = _generation;
    setState(() => _loading = true);
    try {
      final orders = await widget.api.load();
      if (!mounted || generation != _generation) return;
      final gps = _gpsPublisher;
      if (gps?.orderId != null && !orders.any((o) => o.orderId == gps!.orderId)) {
        unawaited(gps!.stop());
      }
      setState(() {
        _orders = orders;
        _error = null;
      });
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _orders = null;
        _error = switch (error) {
          PdHttpStatusException(statusCode: 401) => 'Сеанс закончился. Войди снова.',
          PdHttpStatusException(statusCode: 403) =>
            'Доступ закрыт. Проверь роль и фотоконтроль.',
          PdHttpStatusException(statusCode: 503) =>
            'Тестовый сервер назначений пока недоступен.',
          _ => 'Не удалось загрузить назначения.',
        };
      });
    } finally {
      if (mounted && generation == _generation) {
        setState(() => _loading = false);
        if (widget.visible && _foreground) {
          _refreshTimer = Timer(const Duration(seconds: 10), () {
            unawaited(_refresh());
          });
        }
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _refreshTimer?.cancel();
    final gps = _gpsPublisher;
    if (gps != null) unawaited(gps.stop());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final orders = _orders;
    return ListView(
      key: const Key('pilot-server-orders'),
      padding: const EdgeInsets.all(20),
      children: [
        const Text('Назначенные заказы'),
        const Text('Тестовый сервер · Без оплаты'),
        TextButton.icon(
          key: const Key('pilot-server-orders-refresh'),
          onPressed: _loading ? null : _refresh,
          icon: const Icon(Icons.refresh),
          label: const Text('Обновить'),
        ),
        if (_loading) const LinearProgressIndicator(),
        if (_error != null) Text(_error!),
        if (orders != null && orders.isEmpty)
          const Text('Назначенных заказов нет.'),
        if (orders != null)
          for (final order in orders)
            Card(
              key: ValueKey('pilot-server-order-${order.orderId}'),
              child: ListTile(
                title: Text('${order.origin} → ${order.destination}'),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${order.date} ${order.time} · ${order.statusLabel}'),
                    SelectableText('ID заказа: ${order.orderId}'),
                    if (NativePilotOrdersApi.qaGpsEnabled && !kIsWeb &&
                        (defaultTargetPlatform == TargetPlatform.android ||
                         (NativePilotOrdersApi.qaIosGps && defaultTargetPlatform == TargetPlatform.iOS)))
                      OutlinedButton(
                        key: ValueKey('qa28-gps-${order.orderId}'),
                        onPressed: _gpsStarting || _actingOrderId != null ||
                            (_gpsPublisher?.orderId != null &&
                              _gpsPublisher?.orderId != order.orderId)
                            ? null : () => _toggleGps(order),
                        child: Text(_gpsPublisher?.orderId == order.orderId
                            ? 'Остановить передачу GPS'
                            : 'Передавать GPS диспетчеру · QA'),
                      ),
                    if (order.waitingSeconds > 0 || order.waitingActive)
                      Text('Остановка: ${order.waitingSeconds} сек · QA: ${(order.stopChargeCents / 100).toStringAsFixed(2)} €'),
                    FilledButton(
                      key: ValueKey('pilot-trip-control-${order.orderId}'),
                      onPressed: _actingOrderId != null || _loading ? null : () async {
                        final action = switch (order.status) {
                          'assigned' => 'approach',
                          'approaching' => 'arrive',
                          'arrived' => 'start',
                          _ => order.waitingActive ? 'stop_end' : 'stop_start',
                        };
                        if (order.status == 'underway' && !order.waitingActive) {
                          final selected = await showDialog<String>(context: context,
                            builder: (context) => AlertDialog(
                              title: const Text('Управление поездкой'),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(context, 'stop_start'), child: const Text('Остановка')),
                                TextButton(onPressed: () => Navigator.pop(context, 'finish'), child: const Text('Завершить поездку')),
                                TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
                              ],
                            ));
                          if (selected != null && mounted) await _perform(order, selected);
                        } else {
                          await _perform(order, action);
                        }
                      },
                      child: Text(switch (order.status) {
                        'assigned' => 'К пассажиру',
                        'approaching' => 'На месте',
                        'arrived' => 'В путь',
                        _ => order.waitingActive ? 'Продолжить поездку' : 'Управление поездкой',
                      }),
                    ),
                  ],
                ),
              ),
            ),
      ],
    );
  }
}
