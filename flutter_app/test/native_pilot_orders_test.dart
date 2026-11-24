import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../lib/native_pilot_orders.dart';
import '../lib/pd_http_api.dart';
import '../lib/pilot_cabin.dart';

const token = 'synthetic-validator-token-for-unit-test-not-a-secret';
const orderId = '05cdbc84-0930-4c52-baa1-149a03190d78';
const order = {
  'order_id': orderId,
  'from': 'Synthetic origin',
  'to': 'Synthetic destination',
  'trip_date': '2026-12-01',
  'trip_time': '11:30',
  'status': 'assigned',
};

String result(List<Object?> rows) =>
    jsonEncode({'orders': rows, 'payment_mode': 'disabled'});

class RecordingClient extends http.BaseClient {
  RecordingClient(this.handler);

  final http.StreamedResponse Function(http.BaseRequest) handler;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async =>
      handler(request);
}

/// Keep widget timing on controlled Futures; the transport tests
/// exercise real response streams outside Flutter's fake widget clock.
class WidgetOrdersApi extends NativePilotOrdersApi {
  const WidgetOrdersApi(this._read)
      : super(baseUrl: NativePilotOrdersApi.stage, token: token);

  final Future<List<PilotAssignedOrder>> Function() _read;

  @override
  Future<List<PilotAssignedOrder>> load() => _read();
}

void main() {
  test('read uses the staging endpoint and never follows redirects', () async {
    var requestCount = 0;
    final api = NativePilotOrdersApi(
      baseUrl: NativePilotOrdersApi.stage,
      token: token,
      client: RecordingClient((request) {
        requestCount++;
        expect(request.method, 'GET');
        expect(request.url.toString(),
            '${NativePilotOrdersApi.stage}/native-pilot-orders');
        expect(request.headers['authorization'], 'Bearer $token');
        expect(request.followRedirects, isFalse);
        expect(request.contentLength, 0);
        if (requestCount == 1) {
          return http.StreamedResponse(
            Stream.value(utf8.encode(result([order]))), 200,
          );
        }
        return http.StreamedResponse(
          const Stream.empty(), 302, headers: {'location': 'https://elsewhere.invalid'},
        );
      }),
    );
    final rows = await api.load();
    expect(rows.single.orderId, orderId);
    expect(rows.single.statusLabel, 'Назначен');
    await expectLater(
      api.load(),
      throwsA(isA<PdHttpStatusException>().having((e) => e.statusCode, 'status', 302)),
    );
    expect(requestCount, 2);
  });

  test('refuses other hosts and data outside the no-payment contract', () async {
    final other = NativePilotOrdersApi(
      baseUrl: 'https://elsewhere.invalid',
      token: token,
      client: MockClient((_) async {
        fail('Must not send native credentials to any other host');
      }),
    );
    await expectLater(other.load(), throwsFormatException);

    final invalid = [
      '{"orders":[],"payment_mode":"live"}',
      result([{...order, 'order_id': 'not-a-server-uuid'}]),
      result([{...order, 'status': 'requested'}]),
    ];
    for (final body in invalid) {
      final api = NativePilotOrdersApi(
        baseUrl: NativePilotOrdersApi.stage,
        token: token,
        client: MockClient((_) async => http.Response(body, 200)),
      );
      await expectLater(api.load(), throwsFormatException);
    }
  });

  testWidgets('existing pilot cabin shows order id and clears it after denial', (tester) async {
    var requestCount = 0;
    final api = WidgetOrdersApi(() async {
      requestCount++;
      if (requestCount == 1) return [PilotAssignedOrder.parse(order)];
      throw const PdHttpStatusException(403);
    });
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(MaterialApp(home: PilotCabin(assignmentApi: api)));
    await tester.pumpAndSettle();
    expect(requestCount, 1);
    expect(find.byKey(const ValueKey('pilot-server-order-$orderId')), findsOneWidget);
    expect(find.text('ID заказа: $orderId'), findsOneWidget);
    expect(find.text('2026-12-01 11:30 · Назначен'), findsOneWidget);
    expect(find.byKey(const Key('pilot-power-toggle')), findsNothing);
    expect(find.byKey(const Key('pilot-accept-assigned')), findsNothing);

    await tester.tap(find.byKey(const Key('pilot-server-orders-refresh')));
    await tester.pumpAndSettle();
    expect(requestCount, 2);
    expect(find.byKey(const ValueKey('pilot-server-order-$orderId')), findsNothing);
    expect(find.text('Доступ закрыт. Проверь роль и фотоконтроль.'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('backgrounding ignores a late response and refreshes on resume', (tester) async {
    var requestCount = 0;
    final delayed = Completer<List<PilotAssignedOrder>>();
    final api = WidgetOrdersApi(() {
      requestCount++;
      return requestCount == 1 ? delayed.future : Future.value([]);
    });
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(MaterialApp(home: PilotCabin(assignmentApi: api)));
    await tester.pump();
    expect(requestCount, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    delayed.complete([PilotAssignedOrder.parse(order)]);
    await tester.pump();
    expect(requestCount, 1);
    expect(find.byKey(const ValueKey('pilot-server-order-$orderId')), findsNothing);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('Назначенных заказов нет.'), findsOneWidget);
    expect(requestCount, 2);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
