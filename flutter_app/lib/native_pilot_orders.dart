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
  });

  final String orderId;
  final String origin;
  final String destination;
  final String date;
  final String time;
  final String status;

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

/// Server-truth projection within the existing pilot cabin, not a trip demo.
/// Reads only when mounted in the foreground; never invokes mutable actions.
class PilotAssignedOrdersPanel extends StatefulWidget {
  const PilotAssignedOrdersPanel({super.key, required this.api});

  final NativePilotOrdersApi api;

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
        oldWidget.api.token != widget.api.token) {
      _forget();
      unawaited(_refresh());
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
    if (!_foreground || _loading) return;
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
        if (_foreground) {
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
                  ],
                ),
              ),
            ),
      ],
    );
  }
}
