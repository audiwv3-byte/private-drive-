import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/native_orders_api.dart';
import 'package:private_drive/passenger_demo.dart';

void main() {
  testWidgets('main passenger booking uses bearer server order and never creates a demo trip',
      (tester) async {
    final store = DemoTripStore();
    var sends = 0;
    http.Request? received;
    final api = NativeOrdersApi('https://qa.example.invalid', 'synthetic-passenger-token',
      client: MockClient((request) async {
        sends++;
        received = request;
        return http.Response('{"order_id":"qa-confirmed-server-id",'
            '"payment_mode":"disabled"}', 201);
      }),
    );
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false, tripStore: store, ordersApi: api)));
    final scroller = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(find.byKey(const Key('route-kaunas')),
        150, scrollable: scroller);
    await tester.tap(find.byKey(const Key('route-kaunas')));
    await tester.pump();
    await tester.scrollUntilVisible(
        find.byKey(const Key('passenger-book-disabled')),
        200, scrollable: scroller);
    final submit = tester.widget<FilledButton>(
      find.byKey(const Key('passenger-book-disabled')));
    expect(submit.onPressed, isNotNull);
    submit.onPressed!();
    await tester.pumpAndSettle();
    expect(sends, 1);
    expect(received?.method, 'POST');
    expect(received?.url.path, '/native-orders');
    expect(received?.headers['authorization'], 'Bearer synthetic-passenger-token');
    final data = jsonDecode(received!.body) as Map<String, dynamic>;
    expect(data.keys.toSet(), {'request_id','from','to','trip_date','trip_time'});
    expect(data['from'], 'Вильнюс');
    expect(data['to'], 'Каунас');
    expect(data.containsKey('payment_method'), false);
    expect(store.trip, isNull);
    expect(find.text('Заявка получена диспетчерской'), findsOneWidget);
    expect(find.textContaining('qa-confirmed-server-id'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('failed server booking never creates local trip',
      (tester) async {
    final store = DemoTripStore();
    final api = NativeOrdersApi('https://qa.example.invalid', 'synthetic-passenger-token',
      client: MockClient((_) async =>
          http.Response('{"error":"storage_unavailable"}',503)));
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false, tripStore: store, ordersApi: api)));
    final scrollable = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(find.byKey(const Key('route-kaunas')),
        150, scrollable: scrollable);
    await tester.tap(find.byKey(const Key('route-kaunas')));
    await tester.pump();
    await tester.scrollUntilVisible(
        find.byKey(const Key('passenger-book-disabled')),
        200, scrollable: scrollable);
    tester.widget<FilledButton>(
      find.byKey(const Key('passenger-book-disabled'))).onPressed!();
    await tester.pumpAndSettle();
    expect(store.trip, isNull);
    expect(find.text('Заявка не отправлена'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
