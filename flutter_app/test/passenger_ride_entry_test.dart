import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_demo.dart';
import 'package:private_drive/passenger_ride_entry.dart';
import 'package:private_drive/app_language.dart';

void main() {
  testWidgets('PD logo and exactly two ride choices appear on the entry screen', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerRideEntry(enableMapTiles: false, tripStore: store),
    ));
    final logo = find.byKey(const Key('private-drive-brand-logo'));
    expect(logo, findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-advance-booking')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-vilnius-panorama')), findsNothing);
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    final transfer = find.byKey(const Key('passenger-entry-transfer'));
    await tester.scrollUntilVisible(transfer, 180);
    expect(transfer, findsOneWidget);
    expect(find.byType(ListTile), findsNWidgets(2));
    expect(find.byKey(const Key('passenger-entry-delivery')), findsNothing);
  });

  testWidgets('Passenger language picker changes all screens without returning to login',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    addTearDown(() => pdLanguage.set('RU', persist: false));
    pdLanguage.set('RU', persist: false);
    await tester.pumpWidget(PdLanguageScope(
      language: pdLanguage,
      child: MaterialApp(
        home: PdPassengerLanguageScope(
          child: PassengerRideEntry(enableMapTiles: false, tripStore: store),
        ),
      ),
    ));
    await tester.tap(find.byKey(const Key('passenger-global-language-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('passenger-select-language-LT')));
    await tester.pumpAndSettle();
    expect(find.text('Pasirink kelionės tipą'), findsOneWidget);
    expect(pdLanguage.value, 'LT');

    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-transfer')), 180);
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(
      find.byKey(const Key('passenger-selected-ride-type'))).data, 'Pervežimas');

    await tester.tap(find.byKey(const Key('passenger-global-language-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('passenger-select-language-EN')));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(
      find.byKey(const Key('passenger-selected-ride-type'))).data, 'Transfer');
    expect(pdLanguage.value, 'EN');
    await tester.pageBack();
    await tester.pumpAndSettle();
    // Return to the hero after scrolling down to the transfer option.
    await tester.drag(find.byType(SingleChildScrollView).first, const Offset(0, 460));
    await tester.pumpAndSettle();
    expect(find.text('Choose ride type'), findsOneWidget);
  });

  testWidgets('Selected language persists across ride entry and booking route',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    addTearDown(() => pdLanguage.set('RU', persist: false));
    pdLanguage.set('LT', persist: false);
    await tester.pumpWidget(PdLanguageScope(
      language: pdLanguage,
      child: MaterialApp(
        home: PdPassengerLanguageScope(
          child: PassengerRideEntry(enableMapTiles: false, tripStore: store),
        ),
      ),
    ));
    expect(find.text('Pasirink kelionės tipą'), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-transfer')), 180);
    expect(find.text('Pervežimas'), findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(
      find.byKey(const Key('passenger-selected-ride-type'))).data, 'Pervežimas');
    final form = find.descendant(of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable)).first;
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-round-trip')),
      160, scrollable: form);
    expect(find.text('Pirmyn ir atgal'), findsOneWidget);
    pdLanguage.set('EN', persist: false);
    await tester.pumpAndSettle();
    expect(find.text('Round trip'), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-selected-ride-type')),
      -160, scrollable: form);
    expect(tester.widget<Text>(
      find.byKey(const Key('passenger-selected-ride-type'))).data, 'Transfer');
  });

  testWidgets('Language selection never translates pilot or dispatcher UI',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    addTearDown(() => pdLanguage.set('RU', persist: false));
    pdLanguage.set('LT', persist: false);
    await tester.pumpWidget(PdLanguageScope(
      language: pdLanguage,
      child: MaterialApp(
        home: Builder(builder: (context) => Column(children: [
          Text(pdLabel(context, 'Кабина пилота')),
          Text(pdLabel(context, 'Кабинет диспетчера · демо')),
          Text(pdTr(context, 'Выйти на линию', 'Prisijungti', 'Go online')),
        ])),
      ),
    ));
    expect(find.text('Кабина пилота'), findsOneWidget);
    expect(find.text('Кабинет диспетчера · демо'), findsOneWidget);
    expect(find.text('Выйти на линию'), findsOneWidget);
    expect(find.text('Vairuotojo kabina'), findsNothing);
    pdLanguage.set('EN', persist: false);
    await tester.pump();
    expect(find.text('Кабина пилота'), findsOneWidget);
    expect(find.text('Кабинет диспетчера · демо'), findsOneWidget);
    expect(find.text('Go online'), findsNothing);
  });

  testWidgets('Passenger chooses taxi before seeing booking form', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerRideEntry(enableMapTiles: false, tripStore: store),
    ));
    expect(find.byKey(const Key('passenger-entry-title')), findsOneWidget);
    expect(find.byKey(const Key('pilot-offline-vilnius-background')), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-transfer')), 180);
    expect(find.descendant(
      of: find.byKey(const Key('passenger-entry-transfer')),
      matching: find.byIcon(Icons.directions_car_filled),
    ), findsOneWidget);
    expect(find.descendant(
      of: find.byKey(const Key('passenger-entry-transfer')),
      matching: find.byIcon(Icons.airport_shuttle),
    ), findsNothing);
    expect(find.byKey(const Key('passenger-form')), findsNothing);
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-taxi')), -180);
    await tester.tap(find.byKey(const Key('passenger-entry-taxi')));
    await tester.pumpAndSettle();
    expect(find.byType(PassengerDemo), findsOneWidget);
    expect(tester.widget<Text>(
      find.byKey(const Key('passenger-selected-ride-type'))).data, 'Такси');
    expect(find.byKey(const Key('passenger-taxi-tariffs')), findsNothing);
    expect(tester.getTopLeft(find.byKey(const Key('passenger-date'))).dy,
      greaterThan(tester.getTopLeft(find.byKey(const Key('passenger-selected-ride-type'))).dy));
    expect(find.byKey(const Key('passenger-time')), findsOneWidget);
    expect(find.byKey(const Key('passenger-round-trip')), findsNothing);
    expect(find.byKey(const Key('passenger-ride-type')), findsNothing);
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
    expect(find.byKey(const Key('passenger-map-day-night')), findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-open-drawer')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('passenger-drawer-fares')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-taxi-tariffs')), findsOneWidget);
    expect(find.byKey(const Key('passenger-transfer-tariffs')), findsOneWidget);
  });

  testWidgets('Passenger chooses transfer on dedicated entry screen', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerRideEntry(enableMapTiles: false, tripStore: store),
    ));
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-entry-transfer')), 180);
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(
      find.byKey(const Key('passenger-selected-ride-type'))).data, 'Трансфер');
    expect(tester.getTopLeft(find.byKey(const Key('passenger-date'))).dy,
      greaterThan(tester.getTopLeft(find.byKey(const Key('passenger-selected-ride-type'))).dy));
    await tester.scrollUntilVisible(find.byKey(const Key('passenger-round-trip')), 160,
      scrollable: find.descendant(of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable)).first);
    expect(find.byKey(const Key('passenger-round-trip')), findsOneWidget);
  });
}
