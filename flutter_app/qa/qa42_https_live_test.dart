import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/io_client.dart';

import '../lib/native_orders_api.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/pd_http_api.dart';

void main() {
  test('native order reaches dispatcher and pilot over HTTPS', () async {
    final env = Platform.environment;
    const base = String.fromEnvironment('PD_NATIVE_AUTH_API_URL');
    final uri = Uri.parse(base);
    expect(uri.scheme, 'https');
    expect(uri.host, '127.0.0.1');
    final context = SecurityContext(withTrustedRoots: false)
      ..setTrustedCertificates(env['QA39_CERT']!);
    final client = IOClient(HttpClient(context: context));
    addTearDown(client.close);

    final passenger = NativeOrdersApi(base, env['QA39_PASSENGER_TOKEN']!, client: client);
    final otherPassenger =
        NativeOrdersApi(base, env['QA39_OTHER_PASSENGER_TOKEN']!, client: client);
    final pilot = NativePilotOrdersApi(
      baseUrl: base,
      token: env['QA39_PILOT_TOKEN']!,
      client: client,
    );
    final dispatch = {'X-Telegram-Init-Data': env['QA39_DISPATCH_INIT_DATA']!};
    Map<String, dynamic> decode(String body) =>
        jsonDecode(body) as Map<String, dynamic>;

    final auth = uri.resolve('/native-auth/session');
    final session = await client.post(auth, headers: {
      'Authorization': 'Bearer ${env['QA39_PASSENGER_TOKEN']}',
    });
    expect(session.statusCode, 200);
    expect(decode(session.body)['role'], 'passenger');
    expect((await client.post(auth)).statusCode, 401);
    final pilotSession = await client.post(auth, headers: {
      'Authorization': 'Bearer ${env['QA39_PILOT_TOKEN']}',
    });
    expect(decode(pilotSession.body)['role'], 'pilot');
    expect(await pilot.load(), isEmpty);
    final order = await passenger({
      'request_id': NativeOrdersApi.requestId(),
      'from': 'Synthetic Vilnius A',
      'to': 'Synthetic Vilnius B',
      'trip_date': '2030-01-01',
      'trip_time': '12:00',
      'details': {
        'ride_type': 'transfer',
        'round_trip': false,
        'extras': <String>[],
      },
    });
    final id = order['order_id'] as String;
    expect(order['status'], 'requested');
    expect((await otherPassenger())['orders'], isEmpty);

    final queue = uri.resolve('/dispatch/orders/state');
    expect((await client.get(queue)).statusCode, 401);
    final listed = await client.get(queue, headers: dispatch);
    expect(listed.statusCode, 200);
    final queuedOrder = (decode(listed.body)['orders'] as List<dynamic>).single;
    expect(queuedOrder['id'], id);
    expect(queuedOrder['origin'], 'Synthetic Vilnius A');

    final assigned = await client.post(
      uri.resolve('/dispatch/orders/$id/assign'),
      headers: dispatch,
      body: {'pilot_id': 'qa39-pilot', 'csrf': env['QA39_CSRF']!},
    );
    expect(assigned.statusCode, 200, reason: assigned.body);
    final active = (await pilot.load()).single;
    expect(active.orderId, id);
    expect(active.status, 'assigned');

    await expectLater(
      NativePilotOrdersApi(
        baseUrl: base,
        token: env['QA39_PASSENGER_TOKEN']!,
        client: client,
      ).load(),
      throwsA(isA<PdHttpStatusException>().having((e) => e.statusCode, 'status', 403)),
    );

    final gps = uri.resolve('/native-pilot-orders/$id/gps');
    final gpsHeaders = {'Authorization': 'Bearer ${env['QA39_PILOT_TOKEN']}', 'Content-Type': 'application/json'};
    final stamp = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    final fix = jsonEncode({'enabled':true,'captured_at':stamp,'latitude':54.6872,'longitude':25.2797});
    expect((await client.post(gps, headers: gpsHeaders, body: fix)).statusCode, 200);
    final dispatchGps = uri.resolve('/dispatch/orders/$id/gps');
    expect((await client.get(dispatchGps)).statusCode,401);
    expect((await client.get(dispatchGps, headers: dispatch)).statusCode,200);
    expect((await client.post(gps,headers:gpsHeaders,body:jsonEncode({'enabled':false,'captured_at':stamp+1}))).statusCode,200);
    for (final step in const {
      'approach': 'approaching',
      'arrive': 'arrived',
      'start': 'underway',
      'finish': 'finished',
    }.entries) {
      final result = await pilot.action(id, step.key);
      expect(result['status'], step.value);
    }
    expect(await pilot.load(), isEmpty);
    final history = ((await passenger())['orders'] as List<dynamic>).single;
    expect(history['order_id'], id);
    expect(history['status'], 'finished');
    final logout = await client.post(uri.resolve('/native-auth/sign-out'), headers: {'Authorization':'Bearer ${env['QA39_PASSENGER_TOKEN']}'});
    expect(logout.statusCode,200);
    expect((await client.post(auth,headers:{'Authorization':'Bearer ${env['QA39_PASSENGER_TOKEN']}'})).statusCode,401);
  });
}
