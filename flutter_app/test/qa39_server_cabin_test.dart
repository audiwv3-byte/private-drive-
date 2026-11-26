import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../lib/native_server_cabin.dart';
import '../lib/native_orders_api.dart';
import '../lib/passenger_ride_entry.dart';

void main() {
  testWidgets('authenticated passenger has no local trip store or delivery',
      (tester) async {
    await tester.pumpWidget(MaterialApp(home: NativeServerCabin(
      ordersApi: NativeOrdersApi('https://qa.invalid', 'synthetic-token'),
      enableMapTiles: false,
    )));
    final entry = tester.widget<PassengerRideEntry>(find.byType(PassengerRideEntry));
    expect(entry.tripStore, isNull);
    expect(entry.ordersApi, isNotNull);
    final delivery = tester.widget<ListTile>(
      find.byKey(const Key('passenger-entry-delivery')));
    expect(delivery.onTap, isNull);
  });
}
