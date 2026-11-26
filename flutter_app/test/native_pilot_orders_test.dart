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

  @override
  Future<bool> availability([bool? desiredOnline]) async => false;
}

class FakeAvailabilityApi extends NativePilotOrdersApi {
  FakeAvailabilityApi() : super(baseUrl: NativePilotOrdersApi.stage, token: token);
  bool serverOnline = false;
  bool failNextToggle = false;
  int heartbeatCalls = 0;

  @override
  Future<bool> availability([bool? desiredOnline]) async {
    if (desiredOnline != null) {
      if (failNextToggle) {
        failNextToggle = false;
        throw const PdHttpStatusException(503);
      }
      serverOnline = desiredOnline;
      if (desiredOnline) heartbeatCalls++;
    }
    return serverOnline;
  }
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

  test('pilot trip actions require staging Bearer and server acknowledgement', () async {
    final api = NativePilotOrdersApi(
      baseUrl: NativePilotOrdersApi.stage,
      token: token,
      client: MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/native-pilot-orders');
        expect(request.followRedirects, isFalse);
        expect(request.headers['authorization'], 'Bearer $token');
        final body = jsonDecode(request.body);
        expect(body, {'order_id': orderId, 'action': 'approach'});
        return http.Response(jsonEncode({
          'order_id': orderId, 'status': 'approaching',
          'payment_mode': 'disabled', 'waiting_seconds': 0,
        }), 200);
      }),
    );
    expect((await api.action(orderId, 'approach'))['status'], 'approaching');
    await expectLater(api.action(orderId, 'pay'), throwsFormatException);
    await expectLater(api.action('bad-order', 'approach'), throwsFormatException);
  });

  testWidgets('connected POWER uses only server-acknowledged state and foreground heartbeat',
      (tester) async {
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final api = FakeAvailabilityApi();
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: PilotServerAvailabilityButton(api: api))));
    await tester.pumpAndSettle();
    expect(find.text('НЕ НА ЛИНИИ'), findsOneWidget);
    expect(api.serverOnline, false);

    await tester.tap(find.byKey(const Key('pilot-server-line-toggle')));
    await tester.pumpAndSettle();
    expect(find.text('НА ЛИНИИ'), findsOneWidget);
    expect(api.serverOnline, true);
    final count = api.heartbeatCalls;
    await tester.pump(const Duration(seconds: 46));
    await tester.pump();
    expect(api.heartbeatCalls, greaterThan(count));

    api.failNextToggle = true;
    await tester.tap(find.byKey(const Key('pilot-server-line-toggle')));
    await tester.pumpAndSettle();
    expect(find.text('СТАТУС НЕИЗВЕСТЕН'), findsOneWidget);
    expect(find.byKey(const Key('pilot-server-line-toggle')),
      findsOneWidget);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('pilot-server-line-toggle'))).onPressed, isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test('server availability is never inferred from local toggle', () async {
    final methods = <String>[];
    final api = NativePilotOrdersApi(
      baseUrl: NativePilotOrdersApi.stage,
      token: token,
      client: MockClient((request) async {
        methods.add(request.method);
        expect(request.url.path, '/native-pilot-availability');
        expect(request.followRedirects, isFalse);
        expect(request.headers['authorization'], 'Bearer $token');
        if (request.method == 'PATCH') {
          expect(jsonDecode(request.body), {'online': true});
          return http.Response('{"online":true,"payment_mode":"disabled"}', 200);
        }
        return http.Response('{"online":false,"payment_mode":"disabled"}', 200);
      }),
    );
    expect(await api.availability(), false);
    expect(await api.availability(true), true);
    expect(methods, ['GET', 'PATCH']);
    final unconfirmed = NativePilotOrdersApi(
      baseUrl: NativePilotOrdersApi.stage, token: token,
      client: MockClient((_) async =>
        http.Response('{"online":false,"payment_mode":"disabled"}', 200)),
    );
    await expectLater(unconfirmed.availability(true), throwsFormatException);
    await expectLater(unconfirmed.availability(false), completes);
    final forbidden = NativePilotOrdersApi(
      baseUrl: 'https://elsewhere.invalid', token: token,
      client: MockClient((_) async {
        fail('Bearer must not reach untrusted server');
      }),
    );
    await expectLater(forbidden.availability(), throwsFormatException);
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
    await tester.pumpWidget(MaterialApp(home: PilotCabin(assignmentApi: api, enableMapTiles: false)));
    await tester.tap(find.byKey(const Key('pilot-assigned-trips')));
    await tester.pump();
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
    await tester.pumpWidget(MaterialApp(home: PilotCabin(assignmentApi: api, enableMapTiles: false)));
    await tester.tap(find.byKey(const Key('pilot-assigned-trips')));
    await tester.pump();
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
