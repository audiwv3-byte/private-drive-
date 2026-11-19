import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_ride_entry.dart';
import 'package:private_drive/passenger_extra_services.dart';

void main() {
  testWidgets('Passenger menu contains both standalone 20 EUR services',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerRideEntry(
      enableMapTiles: false, tripStore: store)));
    expect(find.byKey(const Key('passenger-entry-jumpstart')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-entry-delivery')), 160,
      scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('passenger-entry-delivery')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('passenger-entry-jumpstart')));
    await tester.tap(find.byKey(const Key('passenger-entry-jumpstart')));
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
