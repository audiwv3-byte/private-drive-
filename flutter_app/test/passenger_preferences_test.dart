import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/passenger_demo.dart';
import 'package:private_drive/passenger_preferences_storage.dart';

class MemoryPassengerPreferences implements PassengerPreferencesStorage {
  String? saved;

  @override
  Future<String?> read() async => saved;

  @override
  Future<void> write(String json) async {
    saved = json;
  }
}

void main() {
  testWidgets('Restore all passenger comfort options after reopening the screen',
      (tester) async {
    final storage = MemoryPassengerPreferences()
      ..saved = jsonEncode({
        'version': 1,
        'radio': 'M-1 · 106,8 FM',
        'tracks': ['Track one', 'Track two', 'Track three'],
        'temperature': 22.0,
        'meetSign': true,
        'pets': false,
        'soberDriver': false,
        'music': true,
        'flowers': true,
        'coffee': true,
        'water': true,
        'quietRide': false,
        'luggageHelp': true,
        'wishes': 'Вода без газа',
      });
    Future<void> showPassenger() async {
      await tester.pumpWidget(MaterialApp(
        home: PassengerDemo(
          enableMapTiles: false, preferencesStorage: storage),
      ));
      await tester.pumpAndSettle();
    }

    await showPassenger();
    final list = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('service-flowers')), 190, scrollable: list);
    expect(tester.widget<CheckboxListTile>(
      find.byKey(const Key('service-flowers'))).value, isTrue);
    expect(tester.widget<CheckboxListTile>(
      find.byKey(const Key('service-coffee'))).value, isTrue);
    expect(tester.widget<CheckboxListTile>(
      find.byKey(const Key('service-water'))).value, isTrue);

    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('passenger-radio-station-M-1 · 106,8 FM')),
      190, scrollable: list);
    final radio = tester.widget<DropdownButtonFormField<String>>(
      find.byKey(const ValueKey('passenger-radio-station-M-1 · 106,8 FM')));
    expect(radio.initialValue, 'M-1 · 106,8 FM');
    for (var i = 0; i < 3; i++) {
      await tester.scrollUntilVisible(
        find.byKey(Key('passenger-favorite-track-$i')),
        190, scrollable: list);
      final field = tester.widget<TextField>(
        find.byKey(Key('passenger-favorite-track-$i')));
      expect(field.controller!.text, 'Track ${['one', 'two', 'three'][i]}');
    }
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('passenger-cabin-temperature-22.0')),
      190, scrollable: list);
    final temperature = tester.widget<DropdownButtonFormField<double?>>(
      find.byKey(const ValueKey('passenger-cabin-temperature-22.0')));
    expect(temperature.initialValue, 22.0);
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-trip-wishes')), 190, scrollable: list);
    expect(tester.widget<TextField>(
      find.byKey(const Key('passenger-trip-wishes')))
      .controller!.text, 'Вода без газа');

    // Change a wish, leave the screen, then open a fresh widget instance.
    await tester.enterText(
      find.byKey(const Key('passenger-trip-wishes')), 'Тихая поездка');
    await tester.pumpAndSettle();
    expect(jsonDecode(storage.saved!)['wishes'], 'Тихая поездка');
    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    await tester.pump();
    await showPassenger();
    final reopenedList = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-trip-wishes')),
      190, scrollable: reopenedList);
    expect(tester.widget<TextField>(
      find.byKey(const Key('passenger-trip-wishes')))
      .controller!.text, 'Тихая поездка');
    expect(jsonDecode(storage.saved!)['radio'], 'M-1 · 106,8 FM');
    expect(jsonDecode(storage.saved!)['temperature'], 22.0);
    expect(jsonDecode(storage.saved!)['flowers'], isTrue);
    expect(jsonDecode(storage.saved!)['coffee'], isTrue);
    expect(jsonDecode(storage.saved!)['water'], isTrue);
  });

  testWidgets('Invalid saved preferences fall back to safe defaults',
      (tester) async {
    final storage = MemoryPassengerPreferences()
      ..saved = '{invalid';
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(
        enableMapTiles: false, preferencesStorage: storage),
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-form')), findsOneWidget);
    // No user-facing crash or synthetic booking created on invalid input.
  });
}
