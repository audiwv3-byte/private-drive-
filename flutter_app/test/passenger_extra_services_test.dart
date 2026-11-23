import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_ride_entry.dart';
import 'package:private_drive/passenger_extra_services.dart';

void main() {
  testWidgets('New extra-service orders never offer cash payment',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerExtraServices(
      type: ExtraServiceType.jumpstart, tripStore: store)));
    await tester.scrollUntilVisible(
      find.byKey(const Key('extra-payment-Карта')), 160,
      scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('extra-payment-Наличные')), findsNothing);
    expect(find.byKey(const Key('extra-payment-PayPal')), findsOneWidget);
  });

  testWidgets('Passenger booking includes assistance and delivery options',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerRideEntry(
      enableMapTiles: false, tripStore: store)));
    // Standalone delivery is on the entry screen; assistance is on the
    // subsequent booking screen as requested.
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-delivery')), 180);
    expect(find.byKey(const Key('passenger-entry-delivery')), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-taxi')), -180);
    await tester.tap(find.byKey(const Key('passenger-entry-taxi')));
    await tester.pumpAndSettle();
    final bookingScroll = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-booking-jumpstart')), 160,
      scrollable: bookingScroll);
    final delivery = find.byKey(const Key('passenger-booking-delivery'));
    await tester.scrollUntilVisible(delivery, 160, scrollable: bookingScroll);
    expect(delivery, findsOneWidget);
    final jumpstart = find.byKey(const Key('passenger-booking-jumpstart'));
    await tester.scrollUntilVisible(jumpstart, -160, scrollable: bookingScroll);
    await tester.tap(jumpstart);
    await tester.pumpAndSettle();
    expect(find.text('Запуск автомобиля'), findsWidgets);
    expect(find.byKey(const Key('extra-service-price')), findsOneWidget);
    expect(find.byKey(const Key('extra-service-to')), findsNothing);
  });

  testWidgets('Jumpstart booking requires an address and never charges', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerExtraServices(
      type: ExtraServiceType.jumpstart, tripStore: store)));
    await tester.scrollUntilVisible(
      find.byKey(const Key('extra-service-submit')), 160,
      scrollable: find.byType(Scrollable).first);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('extra-service-submit'))).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('extra-service-from')),
      'Gedimino pr. 1, Vilnius');
    await tester.pump();
    final submit = tester.widget<FilledButton>(
      find.byKey(const Key('extra-service-submit')));
    expect(submit.onPressed, isNotNull);
    submit.onPressed!();
    await tester.pumpAndSettle();
    expect(store.trip!.rideType, 'Запуск автомобиля');
    expect(store.trip!.estimatedFareEur, 20);
    expect(store.trip!.to, 'Помощь на месте');
    expect(store.trip!.paymentMethod, 'Карта');
  });

  testWidgets('Delivery needs shop and destination and uses 20 EUR base', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerExtraServices(
      type: ExtraServiceType.delivery, tripStore: store)));
    await tester.enterText(find.byKey(const Key('extra-service-from')),
      'Магазин, Вильнюс');
    await tester.scrollUntilVisible(
      find.byKey(const Key('extra-service-submit')), 160,
      scrollable: find.byType(Scrollable).first);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('extra-service-submit'))).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('extra-service-to')),
      'Дом, Вильнюс');
    await tester.pump();
    final submit = tester.widget<FilledButton>(
      find.byKey(const Key('extra-service-submit')));
    expect(submit.onPressed, isNotNull);
    submit.onPressed!();
    await tester.pumpAndSettle();
    expect(store.trip!.rideType, 'Доставка товаров');
    expect(store.trip!.estimatedFareEur, 20);
    expect(store.trip!.from, 'Магазин, Вильнюс');
    expect(store.trip!.to, 'Дом, Вильнюс');
    expect(store.trip!.services, contains('Доставка товаров'));
  });
}
