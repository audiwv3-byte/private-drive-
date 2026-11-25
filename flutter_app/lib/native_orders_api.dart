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
  Future<Map<String,dynamic>> call([Map<String,String>? payload]) async {
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
      setState(() => result = widget.api.call());
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
        setState(() => result = widget.api.call());
      })
    ]),
    body: FutureBuilder<Map<String,dynamic>>(future: result, builder: (context, snapshot) {
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
            subtitle: Text("${row['trip_date']} ${row['trip_time']} · ${row['status']}"),
            trailing: const Text('Без оплаты'))
      ]);
    }));
}
