import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'pd_http_api.dart';

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
  });

  final String orderId;
  final String origin;
  final String destination;
  final String date;
  final String time;
  final String status;
  final int waitingSeconds;
  final bool waitingActive;

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
        !(const {'assigned', 'approaching', 'underway'}.contains(status))) {
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
    );
  }

  String get statusLabel => switch (status) {
    'assigned' => 'Назначен',
    'approaching' => 'Пилот едет к пассажиру',
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

  Future<bool> availability([bool? desiredOnline]) async {
    if (baseUrl != stage) {
      throw const FormatException('Pilot availability requires staging');
    }
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    final client = _client ?? http.Client();
    try {
      final request = http.Request(
        desiredOnline == null ? 'GET' : 'PATCH',
        PdHttpApi.secureUri(baseUrl, '/native-pilot-availability'))
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
    if (baseUrl != stage) {
      throw const FormatException('Pilot trip actions require staging');
    }
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    if (!PilotAssignedOrder._uuid.hasMatch(orderId) ||
        !const {'approach', 'start', 'finish', 'stop_start', 'stop_end'}.contains(action)) {
      throw const FormatException('Invalid trip action');
    }
    final client = _client ?? http.Client();
    try {
      final request = http.Request(
        'PATCH', PdHttpApi.secureUri(baseUrl, '/native-pilot-orders'))
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
          !const {'approaching', 'underway', 'finished'}.contains(data['status'])) {
        throw const FormatException('Invalid trip acknowledgement');
      }
      return data;
    } finally {
      if (_client == null) client.close();
    }
  }

  Future<List<PilotAssignedOrder>> load() async {
    if (baseUrl != stage) {
      throw const FormatException('Pilot assignments require the staging API');
    }
    if (token.length < 40 || token.length > 256 || RegExp(r'\s').hasMatch(token)) {
      throw const PdHttpStatusException(401);
    }
    final request = http.Request(
      'GET', PdHttpApi.secureUri(baseUrl, '/native-pilot-orders'),
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
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
      _read();
    } else if (mounted) {
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

  Future<void> _perform(PilotAssignedOrder order, String action) async {
    if (_actingOrderId != null || _loading) return;
    setState(() { _actingOrderId = order.orderId; _error = null; });
    try {
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
                    if (order.waitingSeconds > 0 || order.waitingActive)
                      Text('Ожидание: ${order.waitingSeconds} сек · '
                          'начатые минуты оплачиваемого ожидания: '
                          '${(order.waitingSeconds + 59) ~/ 60}'
                          '${order.waitingActive ? ' · таймер идёт' : ''}'),
                    if (order.status == 'assigned')
                      FilledButton(
                        key: ValueKey('pilot-trip-approach-${order.orderId}'),
                        onPressed: _actingOrderId != null ? null :
                            () => _perform(order, 'approach'),
                        child: const Text('К пассажиру'),
                      ),
                    if (order.status == 'approaching')
                      FilledButton(
                        key: ValueKey('pilot-trip-start-${order.orderId}'),
                        onPressed: _actingOrderId != null ? null :
                            () => _perform(order, 'start'),
                        child: const Text('В путь'),
                      ),
                    if (order.status == 'underway') ...[
                      OutlinedButton(
                        key: ValueKey('pilot-trip-stop-${order.orderId}'),
                        onPressed: _actingOrderId != null ? null :
                            () => _perform(order,
                                order.waitingActive ? 'stop_end' : 'stop_start'),
                        child: Text(order.waitingActive
                            ? 'Продолжить поездку' : 'Остановка'),
                      ),
                      FilledButton(
                        key: ValueKey('pilot-trip-finish-${order.orderId}'),
                        onPressed: _actingOrderId != null ? null :
                            () => _perform(order, 'finish'),
                        child: const Text('Завершить'),
                      ),
                    ],
                  ],
                ),
              ),
            ),
      ],
    );
  }
}
