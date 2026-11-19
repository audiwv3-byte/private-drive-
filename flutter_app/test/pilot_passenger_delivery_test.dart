import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_demo.dart';
import 'package:private_drive/pilot_passenger_chat_demo.dart';

DemoTripStore acceptedTrip() {
  final store = DemoTripStore();
  expect(store.create(
    from: 'Вильнюс',
    to: 'Каунас',
    paymentMethod: 'Карта',
    departure: DateTime(2026, 11, 19, 12),
    services: const [],
  ), isTrue);
  expect(store.assignPilot(), isTrue);
  expect(store.acceptAssignedPilot(), isTrue);
  return store;
}

void main() {
  testWidgets('Passenger sees live pilot message and opens its order chat',
      (tester) async {
    final store = acceptedTrip();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerDemo(enableMapTiles: false, tripStore: store),
    ));

    expect(find.byKey(const Key('passenger-pilot-message-alert')), findsNothing);
    expect(store.addPilotChatMessage('Я жду у главного входа'), isTrue);
    await tester.pump();
    expect(find.byKey(const Key('passenger-pilot-message-alert')), findsOneWidget);
    expect(find.text('Я жду у главного входа'), findsWidgets);
    await tester.pump();
    expect(find.byKey(const Key('passenger-pilot-message-popup')), findsOneWidget);

    await tester.tap(find.byKey(const Key('passenger-pilot-message-alert')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('passenger-pilot-message')), findsOneWidget);
    expect(find.text('Я жду у главного входа'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('passenger-chat-input')), 'Выхожу');
    await tester.tap(find.byKey(const Key('passenger-chat-send')));
    await tester.pump();
    expect(store.passengerChatMessages, ['Выхожу']);
  });

  testWidgets('Pilot chat updates when passenger replies and rejects ended trip',
      (tester) async {
    final store = acceptedTrip();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PilotPassengerChatDemo(
        messages: store.pilotChatMessages,
        tripStore: store,
        onSend: store.addPilotChatMessage,
      ),
    ));
    await tester.enterText(find.byKey(const Key('pilot-chat-input')), 'На месте');
    await tester.tap(find.byKey(const Key('pilot-chat-send')));
    await tester.pump();
    expect(store.pilotChatMessages, ['На месте']);
    expect(find.text('На месте'), findsOneWidget);

    expect(store.addPassengerChatMessage('Вижу машину'), isTrue);
    await tester.pump();
    expect(find.text('Пассажир: Вижу машину'), findsOneWidget);

    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    await tester.pump();
    await tester.enterText(find.byKey(const Key('pilot-chat-input')), 'После поездки');
    await tester.tap(find.byKey(const Key('pilot-chat-send')));
    await tester.pump();
    expect(store.pilotChatMessages, ['На месте']);
    expect(tester.widget<TextField>(find.byKey(const Key('pilot-chat-input'))
        .controller!.text, 'После поездки');
  });

  test('Messages never cross isolated orders or unaccepted assignments', () {
    final first = acceptedTrip();
    final second = DemoTripStore();
    addTearDown(first.dispose);
    addTearDown(second.dispose);
    second.create(
      from: 'Вильнюс', to: 'Тракай', paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 19), services: const [],
    );
    second.assignPilot();
    expect(second.addPilotChatMessage('Не должно прийти'), isFalse);
    expect(first.addPilotChatMessage('Только для первого заказа'), isTrue);
    expect(second.pilotChatMessages, isEmpty);
    expect(first.pilotChatMessages, ['Только для первого заказа']);
  });
}
