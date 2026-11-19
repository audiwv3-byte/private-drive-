import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/passenger_demo.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  DemoTripStore activeTrip() {
    final store = DemoTripStore();
    final created = store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 20),
      services: const [],
    );
    expect(created, isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    return store;
  }

  testWidgets('Pilot announces each incoming passenger message once',
      (tester) async {
    final store = activeTrip();
    addTearDown(store.dispose);
    var announces = 0;
    await tester.pumpWidget(MaterialApp(home: PilotDemo(
      enableMapTiles: false,
      tripStore: store,
      onIncomingMessageVoice: () => announces++,
    )));
    expect(store.addPassengerChatMessage('Я выхожу'), isTrue);
    await tester.pump();
    expect(announces, 1);
    expect(store.addPilotChatMessage('Я на месте'), isTrue);
    await tester.pump();
    expect(announces, 1);
    expect(store.addPassengerChatMessage('Уже рядом'), isTrue);
    await tester.pump();
    expect(announces, 2);
    expect(store.passengerChatMessages, ['Я выхожу', 'Уже рядом']);
  });

  testWidgets('Passenger announces pilot messages but never its own messages',
      (tester) async {
    final store = activeTrip();
    addTearDown(store.dispose);
    var announces = 0;
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false,
      tripStore: store,
      onIncomingMessageVoice: () => announces++,
    )));
    await tester.pump();
    expect(store.addPilotChatMessage('Машина приехала'), isTrue);
    await tester.pump();
    expect(announces, 1);
    expect(store.addPassengerChatMessage('Выхожу'), isTrue);
    await tester.pump();
    expect(announces, 1);
    expect(store.addPilotChatMessage('Ожидаю у входа'), isTrue);
    await tester.pump();
    expect(announces, 2);
    expect(store.pilotChatMessages,
      ['Машина приехала', 'Ожидаю у входа']);
  });
}
