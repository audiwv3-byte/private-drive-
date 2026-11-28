import 'dart:convert';

// Use the same MaterialLocalizations as PassengerDemo.
// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/native_orders_api.dart';
import 'package:private_drive/passenger_demo.dart';

void main() {
  testWidgets('QA price is inside checkout, retry preserves payload and invoice matches',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(800, 3000);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    const orderId = '00c69007-fdf1-4e02-bc1f-c2206139766b';
    final attempts = <Map<String, dynamic>>[];
    final api = NativeOrdersApi(
      'https://example.invalid', 'synthetic',
      client: MockClient((request) async {
        expectSync(request.headers['authorization'], 'Bearer synthetic');
        if (request.method == 'POST') {
          attempts.add(jsonDecode(request.body) as Map<String, dynamic>);
          if (attempts.length == 1) return http.Response('{}', 503);
          return http.Response(jsonEncode({
            'order_id': orderId, 'payment_mode': 'disabled',
            'quoted_total_cents': 11500,
          }), 200);
        }
        if (request.url.path == '/native-orders/invoice/$orderId') {
          return http.Response(jsonEncode({
            'order_id': orderId, 'payment_mode': 'disabled',
            'total_cents': 11500, 'currency': 'EUR',
          }), 200);
        }
        expectSync(request.url.path, '/native-orders');
        return http.Response(jsonEncode({
          'payment_mode': 'disabled',
          'orders': [{
            'order_id': orderId, 'from': 'Vilnius', 'to': 'Alytus',
            'trip_date': '2030-01-01', 'trip_time': '12:00',
            'status': 'requested', 'quoted_total_cents': 11500,
            'details': {'payment_method': 'crypto'},
          }],
        }), 200);
      }),
    );
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false, ordersApi: api, initialRideType: 'Трансфер',
    )));
    final form = find.descendant(of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable)).first;
    final origin = find.byKey(const Key('passenger-from'));
    final destination = find.byKey(const Key('passenger-to'));
    await tester.scrollUntilVisible(origin, 250, scrollable: form);
    await tester.enterText(origin, 'Вильнюс');
    await tester.pump();
    expect(tester.widget<TextField>(origin).controller!.text, 'Вильнюс');
    await tester.scrollUntilVisible(destination, 140, scrollable: form);
    final destinationController = tester.widget<TextField>(destination).controller!;
    await tester.enterText(destination, 'Алитус');
    await tester.pump();
    expect(destinationController.text, 'Алитус');
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    final book = find.byKey(const Key('passenger-book-disabled'));
    final price = find.descendant(of: book, matching: find.byKey(const Key('qa-checkout-total')));
    await tester.scrollUntilVisible(book, 200, scrollable: form);
    expect(tester.widget<Text>(price).data, '100.00 €');
    final crypto = find.byKey(const Key('payment-Криптовалюта'));
    final card = find.byKey(const Key('payment-Карта'));
    await tester.scrollUntilVisible(crypto, -150, scrollable: form);
    await tester.tap(crypto);
    await tester.pump();
    await tester.scrollUntilVisible(book, 200, scrollable: form);
    expect(tester.widget<Text>(price).data, '115.00 €');
    await tester.scrollUntilVisible(card, -150, scrollable: form);
    await tester.tap(card);
    await tester.pump();
    await tester.scrollUntilVisible(book, 200, scrollable: form);
    expect(tester.widget<Text>(price).data, '100.00 €');
    await tester.scrollUntilVisible(crypto, -150, scrollable: form);
    await tester.tap(crypto);
    await tester.pump();
    await tester.scrollUntilVisible(book, 200, scrollable: form);
    await tester.tap(book);
    await tester.pumpAndSettle();
    expect(find.text('Повторить прежнюю заявку'), findsOneWidget);
    expect(tester.widget<Text>(price).data, '115.00 €');
    await tester.tap(book);
    await tester.pumpAndSettle();
    expect(attempts, hasLength(2));
    expect(attempts.last, attempts.first);
    expect(attempts.first['details']['payment_method'], 'crypto');
    expect(attempts.first['details'].containsKey('quoted_total_cents'), isFalse);
    expect(find.byType(NativeOrdersHistory), findsOneWidget);
    expect(find.text('Заказ №$orderId'), findsOneWidget);
    await tester.tap(find.text('Тестовый счёт'));
    await tester.pumpAndSettle();
    expect(find.text('Заказ №$orderId\nВсего 115.00 €'), findsOneWidget);
  }, skip: !NativeOrdersApi.qaCheckout);
}
