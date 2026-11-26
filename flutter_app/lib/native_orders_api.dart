import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'pd_http_api.dart';

class NativeOrdersApi {
  NativeOrdersApi(this.baseUrl, this.token, {http.Client? client}) : _client = client;
  final String baseUrl, token;
  final http.Client? _client;
  static String requestId() {
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final h = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${h.substring(0,8)}-${h.substring(8,12)}-${h.substring(12,16)}-${h.substring(16,20)}-${h.substring(20)}';
  }
  Future<Map<String, dynamic>> cancel(String orderId) async {
    final uuid = RegExp(r'^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$');
    if (!uuid.hasMatch(orderId)) {
      throw const FormatException('Invalid order ID');
    }
    final client = _client ?? http.Client();
    try {
      final request = http.Request('PATCH', PdHttpApi.secureUri(baseUrl, '/native-orders'))
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $token'
        ..headers['Content-Type'] = 'application/json'
        ..body = jsonEncode({'order_id': orderId, 'action': 'cancel'});
      final response = await http.Response.fromStream(
        await client.send(request).timeout(const Duration(seconds: 15)))
        .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) throw PdHttpStatusException(response.statusCode);
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is! Map<String, dynamic> ||
          data['payment_mode'] != 'disabled' ||
          data['status'] != 'cancelled' ||
          data['order_id'] != orderId) {
        throw const FormatException('Invalid cancellation acknowledgement');
      }
      return data;
    } finally {
      if (_client == null) client.close();
    }
  }

  Future<Map<String,dynamic>> call([Map<String,dynamic>? payload]) async {
    final uri = PdHttpApi.secureUri(baseUrl, '/native-orders');
    final client = _client ?? http.Client();
    try {
      final request = http.Request(payload == null ? 'GET' : 'POST', uri)
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $token'
        ..headers['Content-Type'] = 'application/json';
      if (payload != null) request.body = jsonEncode(payload);
      final response = await http.Response.fromStream(
        await client.send(request).timeout(const Duration(seconds: 15)))
        .timeout(const Duration(seconds: 15));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw PdHttpStatusException(response.statusCode);
      }
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is! Map<String,dynamic> || data['payment_mode'] != 'disabled') {
        throw const FormatException('Unsafe order response');
      }
      return data;
    } finally {
      if (_client == null) client.close();
    }
  }
}

class NativeOrdersHistory extends StatefulWidget {
  const NativeOrdersHistory({super.key, required this.api});
  final NativeOrdersApi api;
  @override
  State<NativeOrdersHistory> createState() => _NativeOrdersHistoryState();
}
class _NativeOrdersHistoryState extends State<NativeOrdersHistory>
    with WidgetsBindingObserver {
  late Future<Map<String,dynamic>> result = widget.api.call();
  String? _cancelling;
  String? _errorMessage;

  Future<void> _cancel(String orderId) async {
    if (_cancelling != null) return;
    final approved = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Отменить заказ?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialog, false),
            child: const Text('Назад')),
          FilledButton(onPressed: () => Navigator.pop(dialog, true),
            child: const Text('Отменить заказ')),
        ],
      ),
    );
    if (approved != true || !mounted) return;
    setState(() { _cancelling = orderId; _errorMessage = null; });
    try {
      await widget.api.cancel(orderId);
      if (mounted) setState(() { result = widget.api.call(); });
    } catch (_) {
      if (mounted) setState(() => _errorMessage =
          'Заказ не отменён. Проверь соединение и повтори попытку.');
    } finally {
      if (mounted) setState(() => _cancelling = null);
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Show the server's latest status when returning to the app.
    // Never update the booking locally without confirmation from the API.
    if (mounted && state == AppLifecycleState.resumed) {
      setState(() { result = widget.api.call(); });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Мои заказы'), actions: [
      IconButton(icon: const Icon(Icons.refresh), onPressed: () {
        setState(() { result = widget.api.call(); });
      })
    ]),
    body: Column(children: [
      if (_errorMessage != null) Padding(
        padding: const EdgeInsets.all(12),
        child: Text(_errorMessage!, key: const Key('native-cancel-error'))),
      Expanded(child: FutureBuilder<Map<String,dynamic>>(
        future: result, builder: (context, snapshot) {
      if (snapshot.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snapshot.hasError) return const Center(child: Text('Не удалось загрузить заказы. Обнови список.'));
      final rows = snapshot.data?['orders'];
      if (rows is! List) return const Center(child: Text('Некорректный ответ сервера'));
      if (rows.isEmpty) return const Center(child: Text('Заказов пока нет'));
      return ListView(children: [
        for (final row in rows.whereType<Map<String,dynamic>>())
          ListTile(title: Text("${row['from']} → ${row['to']}"),
            subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("${row['trip_date']} ${row['trip_time']} · ${row['status']}"),
                if (row['quote_required'] == true)
                  const Text('Стоимость по запросу'),
                if (row['quoted_total_cents'] is int)
                  Text('Подтверждённый расчёт: '
                      '${((row['quoted_total_cents'] as int) / 100).toStringAsFixed(2)} €'),
                if (row['details'] is Map &&
                    (row['details'] as Map)['extras'] is List &&
                    ((row['details'] as Map)['extras'] as List).isNotEmpty)
                  Text('Дополнительные услуги: '
                      '${((row['details'] as Map)['extras'] as List).join(', ')}'),
              ]),
            trailing: row['order_id'] is String &&
                const {'requested','assigned','approaching'}.contains(row['status'])
                ? TextButton(
                    key: ValueKey('native-cancel-${row['order_id']}'),
                    onPressed: _cancelling != null ? null :
                        () => _cancel(row['order_id'] as String),
                    child: Text(_cancelling == row['order_id']
                        ? 'Отмена…' : 'Отменить'))
                : const Text('Без оплаты'))
      ]);
    }))]));
}
