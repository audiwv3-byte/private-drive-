import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/pilot_passenger_chat_demo.dart';

void main() {
  testWidgets('No passenger chat or call without assigned trip', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, tripStore: store),
    ));
    expect(find.byKey(const Key('pilot-passenger-chat')), findsNothing);
    expect(find.byKey(const Key('pilot-passenger-call')), findsNothing);
    expect(find.byType(PilotPassengerChatDemo), findsNothing);
  });

  testWidgets('Assigned pilot can chat locally but cannot call a real number',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс',
      to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);

    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, tripStore: store),
    ));
    expect(find.byKey(const Key('pilot-passenger-chat')), findsOneWidget);
    expect(find.byKey(const Key('pilot-passenger-call')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-passenger-call')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Реальный звонок не выполняется'), findsOneWidget);
    await tester.tap(find.text('Понятно'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('pilot-passenger-chat')));
    await tester.pumpAndSettle();
    expect(find.byType(PilotPassengerChatDemo), findsOneWidget);
    expect(find.textContaining('не передаются между телефонами'), findsOneWidget);
    await tester.tap(find.text('Я на месте'));
    await tester.pump();
    expect(find.text('Я на месте'), findsNWidgets(2));
    await tester.enterText(find.byKey(const Key('pilot-chat-input')), 'Жду у входа');
    await tester.tap(find.byKey(const Key('pilot-chat-send')));
    await tester.pump();
    expect(find.text('Жду у входа'), findsOneWidget);
    expect(store.pilotChatMessages, contains('Жду у входа'));
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(PilotPassengerChatDemo), findsNothing);
    expect(find.byKey(const Key('pilot-passenger-chat')), findsOneWidget);
    expect(store.pilotChatMessages, contains('Жду у входа'));
    await tester.tap(find.byKey(const Key('pilot-passenger-chat')));
    await tester.pumpAndSettle();
    expect(find.byType(PilotPassengerChatDemo), findsOneWidget);
    expect(tester.widget<PilotPassengerChatDemo>(
      find.byType(PilotPassengerChatDemo),
    ).messages, contains('Жду у входа'));
    expect(find.text('Жду у входа'), findsOneWidget);
  });

  testWidgets('Chat disabled when an assigned trip has finished', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    store.create(
      from: 'Вильнюс',
      to: 'Аэропорт Вильнюса',
      paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 18),
      services: const [],
    );
    store.assignPilot();
    store.acceptAssignedPilot();
    store.advancePilot();
    store.advancePilot();
    store.advancePilot();
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, tripStore: store),
    ));
    expect(find.byKey(const Key('pilot-passenger-chat')), findsNothing);
    expect(find.byKey(const Key('pilot-passenger-call')), findsNothing);
  });
  testWidgets('Underway pilot hears a local next order and can queue it',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    store.create(
      from: 'Вильнюс',
      to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    );
    store.assignPilot();
    store.acceptAssignedPilot();
    var alertCount = 0;

    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(
        enableMapTiles: false,
        tripStore: store,
        onIncomingSound: () => alertCount++,
      ),
    ));
    // Incoming offers are available only during an existing active journey.
    expect(find.byKey(const Key('pilot-simulate-offer')), findsNothing);
    store.advancePilot(); // On the way to pickup
    await tester.pump();
    expect(find.byKey(const Key('pilot-simulate-offer')), findsNothing);
    store.advancePilot(); // Passenger is onboard
    await tester.pump();
    expect(find.byKey(const Key('pilot-simulate-offer')), findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-simulate-offer')));
    await tester.pump();
    expect(alertCount, 1);
    expect(find.byKey(const Key('pilot-next-offer')), findsOneWidget);
    expect(find.text('Вильнюс → Аэропорт Вильнюса'), findsOneWidget);
    expect(find.byKey(const Key('pilot-accept-next')), findsOneWidget);
    expect(find.byKey(const Key('pilot-decline-next')), findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-accept-next')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-next-offer')), findsNothing);
    expect(find.text('Следующий заказ принят · демо'), findsOneWidget);
    expect(store.status, DemoTripStatus.underway);
    expect(find.byKey(const Key('pilot-simulate-offer')), findsNothing);
  });

  testWidgets('Declined next-trip demo offer does not interrupt current trip',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    store.create(
      from: 'Вильнюс',
      to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    );
    store.assignPilot();
    store.acceptAssignedPilot();
    store.advancePilot();
    store.advancePilot();
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(
        enableMapTiles: false,
        tripStore: store,
        onIncomingSound: () {},
      ),
    ));
    await tester.tap(find.byKey(const Key('pilot-simulate-offer')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('pilot-decline-next')));
    await tester.pump();
    expect(store.status, DemoTripStatus.underway);
    expect(find.byKey(const Key('pilot-next-offer')), findsNothing);
    expect(find.byKey(const Key('pilot-simulate-offer')), findsOneWidget);
  });

}
