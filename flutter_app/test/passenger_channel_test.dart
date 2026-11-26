import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/native_orders_api.dart';
import 'package:private_drive/passenger_ride_entry.dart';

void main() {
  testWidgets('signed-in passenger sends the selected ride and opens server history', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    final posted = <Map<String, dynamic>>[];
    final api = NativeOrdersApi('https://example.invalid', 'synthetic', client: MockClient((req) async {
      expectSync(req.url.path, '/native-orders');
      if (req.method == 'POST') {
        posted.add(jsonDecode(req.body) as Map<String, dynamic>);
        return http.Response('{"payment_mode":"disabled","order_id":"synthetic"}', 201);
      }
      return http.Response('{"payment_mode":"disabled","orders":[]}', 200);
    }));
    await tester.pumpWidget(MaterialApp(home: PassengerRideEntry(
      tripStore: store, enableMapTiles: false, ordersApi: api)));
    final transfer = find.byKey(const Key('passenger-entry-transfer'));
    await tester.scrollUntilVisible(transfer, 160);
    await tester.tap(transfer);
    await tester.pumpAndSettle();
    final form = find.descendant(of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable)).first;
    final route = find.byKey(const Key('route-kaunas'));
    await tester.scrollUntilVisible(route, 240, scrollable: form);
    await tester.tap(route);
    await tester.pump();
    final send = find.byKey(const Key('passenger-book-disabled'));
    await tester.scrollUntilVisible(send, 500, scrollable: form);
    await tester.tap(send);
    await tester.pumpAndSettle();
    expect(posted.single['from'], 'Вильнюс');
    expect(posted.single['to'], 'Каунас');
    expect(posted.single['request_id'], isNotEmpty);
    expect(find.byType(NativeOrdersHistory), findsOneWidget);
    expect(store.trip, isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
