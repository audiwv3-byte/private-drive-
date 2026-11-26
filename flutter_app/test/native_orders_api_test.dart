import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_orders_api.dart';

void main() {
  test('POST sends bearer and request ID without payment data', () async {
    final api = NativeOrdersApi('https://example.invalid', 'test-token',
      client: MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/native-orders');
        expect(request.headers['authorization'], 'Bearer test-token');
        expect(request.body, contains('request_id'));
        expect(request.body, isNot(contains('payment')));
        return http.Response('{"order_id":"test","payment_mode":"disabled"}', 201);
      }));
    expect((await api.call({'request_id':NativeOrdersApi.requestId()}))['order_id'], 'test');
  });
  testWidgets('history reloads from server when app returns to foreground',
      (tester) async {
    var reads = 0;
    final api = NativeOrdersApi('https://example.invalid', 'test-token',
      client: MockClient((request) async {
        // A request may resolve during pumpAndSettle; synchronous matcher
        // avoids overlapping Flutter's guarded widget-test operations.
        expectSync(request.method, 'GET');
        reads++;
        return http.Response(
          '{"orders":[{"from":"Vilnius","to":"Airport",'
          '"trip_date":"2026-12-01","trip_time":"12:30",'
          '"status":"${reads == 1 ? 'requested' : 'assigned'}"}],'
          '"payment_mode":"disabled"}',
          200,
        );
      }),
    );
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(MaterialApp(home: NativeOrdersHistory(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('requested'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.textContaining('assigned'), findsOneWidget);
    expect(reads, 2);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test('cancel sends PATCH with bearer and requires server acknowledgement', () async {
    const orderId = '05cdbc84-0930-4c52-baa1-149a03190d78';
    final api = NativeOrdersApi('https://example.invalid', 'test-token',
      client: MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/native-orders');
        expect(request.followRedirects, isFalse);
        expect(request.headers['authorization'], 'Bearer test-token');
        expect(request.body, contains('"action":"cancel"'));
        return http.Response(
          '{"order_id":"05cdbc84-0930-4c52-baa1-149a03190d78",'
          '"status":"cancelled","payment_mode":"disabled"}', 200);
      }));
    expect((await api.cancel(orderId))['status'], 'cancelled');
    await expectLater(api.cancel('invalid'), throwsFormatException);
  });

  test('cancel refuses unconfirmed server status', () async {
    const orderId = '05cdbc84-0930-4c52-baa1-149a03190d78';
    final api = NativeOrdersApi('https://example.invalid', 'test-token',
      client: MockClient((_) async =>
        http.Response('{"status":"requested","payment_mode":"disabled",'
          '"order_id":"05cdbc84-0930-4c52-baa1-149a03190d78"}', 200)));
    await expectLater(api.cancel(orderId), throwsFormatException);
  });

  test('GET rejects unsafe payment mode', () async {
    final api = NativeOrdersApi('https://example.invalid', 'test-token',
      client: MockClient((request) async {
        expect(request.method, 'GET');
        return http.Response('{"orders":[],"payment_mode":"live"}', 200);
      }));
    await expectLater(api.call(), throwsFormatException);
  });
}
