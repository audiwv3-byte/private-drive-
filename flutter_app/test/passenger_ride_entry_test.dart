import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_demo.dart';
import 'package:private_drive/passenger_ride_entry.dart';
import 'package:private_drive/app_language.dart';

void main() {
  testWidgets('PD logo is above original Vilnius panorama and taxi/transfer', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerRideEntry(enableMapTiles: false, tripStore: store),
    ));
    final logo = find.byKey(const Key('private-drive-brand-logo'));
    final panorama = find.byKey(const Key('passenger-entry-vilnius-panorama'));
    expect(logo, findsOneWidget);
    expect(panorama, findsOneWidget);
    expect(tester.getRect(logo).bottom, lessThan(tester.getRect(panorama).top));
    final photo = find.descendant(
      of: panorama, matching: find.byType(Image));
    expect(tester.widget<Image>(photo).image,
      isA<AssetImage>().having((image) => image.assetName,
        'asset name', 'assets/brand/vilnius_cathedral_user_photo.webp'));
    expect(find.byKey(const Key('passenger-entry-taxi')), findsOneWidget);
    expect(find.byKey(const Key('passenger-entry-transfer')), findsOneWidget);
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

    await tester.ensureVisible(find.byKey(const Key('passenger-entry-transfer')));
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(find.text('Bandomasis kelionės užsakymas'), findsOneWidget);

    await tester.tap(find.byKey(const Key('passenger-global-language-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('passenger-select-language-EN')));
    await tester.pumpAndSettle();
    expect(find.text('Demo trip booking'), findsOneWidget);
    expect(pdLanguage.value, 'EN');
    await tester.pageBack();
    await tester.pumpAndSettle();
    // Return to the hero after scrolling down to the transfer option.
    await tester.drag(find.byType(ListView).first, const Offset(0, 460));
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
    expect(find.text('Pervežimas'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('passenger-entry-transfer')));
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(find.text('Bandomasis kelionės užsakymas'), findsOneWidget);
    expect(find.text('Pirmyn ir atgal'), findsOneWidget);
    pdLanguage.set('EN', persist: false);
    await tester.pumpAndSettle();
    expect(find.text('Demo trip booking'), findsOneWidget);
    expect(find.text('Round trip'), findsOneWidget);
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
    expect(find.descendant(
      of: find.byKey(const Key('passenger-entry-transfer')),
      matching: find.byIcon(Icons.directions_car_filled),
    ), findsOneWidget);
    expect(find.descendant(
      of: find.byKey(const Key('passenger-entry-transfer')),
      matching: find.byIcon(Icons.airport_shuttle),
    ), findsNothing);
    expect(find.byKey(const Key('passenger-form')), findsNothing);
    await tester.ensureVisible(find.byKey(const Key('passenger-entry-taxi')));
    await tester.tap(find.byKey(const Key('passenger-entry-taxi')));
    await tester.pumpAndSettle();
    expect(find.byType(PassengerDemo), findsOneWidget);
    expect(find.text('Такси · выбранный тип поездки'), findsOneWidget);
    expect(find.byKey(const Key('passenger-round-trip')), findsNothing);
    expect(find.byKey(const Key('passenger-ride-type')), findsNothing);
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
    expect(find.byKey(const Key('passenger-map-day-night')), findsOneWidget);
  });

  testWidgets('Passenger chooses transfer on dedicated entry screen', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerRideEntry(enableMapTiles: false, tripStore: store),
    ));
    await tester.ensureVisible(find.byKey(const Key('passenger-entry-transfer')));
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(find.text('Трансфер · выбранный тип поездки'), findsOneWidget);
    expect(find.byKey(const Key('passenger-round-trip')), findsOneWidget);
  });
}
