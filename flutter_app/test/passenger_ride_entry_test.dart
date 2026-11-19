import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_demo.dart';
import 'package:private_drive/passenger_ride_entry.dart';
import 'package:private_drive/app_language.dart';

void main() {
  testWidgets('Selected language persists across ride entry and booking route',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    addTearDown(() => pdLanguage.set('RU', persist: false));
    pdLanguage.set('LT', persist: false);
    await tester.pumpWidget(PdLanguageScope(
      language: pdLanguage,
      child: MaterialApp(
        home: PassengerRideEntry(enableMapTiles: false, tripStore: store),
      ),
    ));
    expect(find.text('Pasirink kelionės tipą'), findsOneWidget);
    expect(find.text('Pervežimas'), findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(find.text('Bandomasis kelionės užsakymas'), findsOneWidget);
    expect(find.text('Pirmyn ir atgal'), findsOneWidget);
    pdLanguage.set('EN', persist: false);
    await tester.pumpAndSettle();
    expect(find.text('Demo trip booking'), findsOneWidget);
    expect(find.text('Round trip'), findsOneWidget);
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
    await tester.tap(find.byKey(const Key('passenger-entry-transfer')));
    await tester.pumpAndSettle();
    expect(find.text('Трансфер · выбранный тип поездки'), findsOneWidget);
    expect(find.byKey(const Key('passenger-round-trip')), findsOneWidget);
  });
}
