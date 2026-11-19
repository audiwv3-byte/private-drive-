import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_dispatcher_cabinet.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  testWidgets('Dispatcher alone assigns pending local request', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DemoDispatcherCabinet(tripStore: store),
    ));
    expect(find.byKey(const Key('dispatcher-empty')), findsOneWidget);
    expect(find.byKey(const Key('dispatcher-assign-pilot')), findsNothing);
    expect(find.byKey(const Key('pilot-global-offer')), findsNothing);

    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 18, 15, 30),
      services: const ['Встреча с табличкой'],
    ), isTrue);
    await tester.pump();
    expect(find.byKey(const Key('dispatcher-order-card')), findsOneWidget);
    expect(find.text('Подача: Вильнюс'), findsOneWidget);
    expect(find.text('Назначение: Каунас'), findsOneWidget);
    expect(find.text('Оплата: PayPal'), findsOneWidget);
    expect(store.status, DemoTripStatus.requested);
    expect(find.byKey(const Key('dispatcher-assign-pilot')), findsOneWidget);

    await tester.tap(find.byKey(const Key('dispatcher-assign-pilot')));
    await tester.pump();
    expect(store.status, DemoTripStatus.assigned);
    expect(find.byKey(const Key('dispatcher-assign-pilot')), findsNothing);
    expect(store.assignPilot(), isFalse);
    expect(store.acceptAssignedPilot(), isTrue);
    await tester.pump();
    expect(find.text('Пилот принял заказ'), findsOneWidget);
    expect(store.declineAssignedPilot(), isFalse);
  });

  testWidgets('Dispatcher sees both sides of the chat read-only',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 20),
      services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.addPilotChatMessage('Я подъехал'), isTrue);
    expect(store.addPassengerChatMessage('Сейчас выйду'), isTrue);
    await tester.pumpWidget(MaterialApp(
      home: DemoDispatcherCabinet(
        tripStore: store, enableMapTiles: false,
      ),
    ));
    await tester.ensureVisible(find.byKey(const Key('dispatcher-current-chat')));
    await tester.tap(find.text('Переписка по текущему заказу'));
    await tester.pumpAndSettle();
    expect(find.text('Я подъехал'), findsOneWidget);
    expect(find.text('Сейчас выйду'), findsOneWidget);
    expect(find.textContaining('Только просмотр'), findsOneWidget);
    expect(store.pilotChatMessages, ['Я подъехал']);
    expect(store.passengerChatMessages, ['Сейчас выйду']);
  });

  testWidgets('Multiple archived chats keep distinct panels and messages',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    for (var i = 0; i < 3; i++) {
      expect(store.create(
        from: 'Вильнюс', to: 'Каунас',
        paymentMethod: 'Карта',
        departure: DateTime(2026, 11, 20),
        services: const [],
      ), isTrue);
      expect(store.assignPilot(), isTrue);
      expect(store.acceptAssignedPilot(), isTrue);
      expect(store.addPilotChatMessage('Пилот номер $i'), isTrue);
      expect(store.addPassengerChatMessage('Ответ номер $i'), isTrue);
      expect(store.cancelByPassenger(), isTrue);
    }
    expect(store.create(
      from: 'Каунас', to: 'Вильнюс',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 21),
      services: const [],
    ), isTrue);
    expect(store.archivedChats, hasLength(3));

    await tester.pumpWidget(MaterialApp(home: DemoDispatcherCabinet(
      tripStore: store, enableMapTiles: false,
    )));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    for (var i = 0; i < 3; i++) {
      final panel = find.byKey(Key('dispatcher-archived-chat-$i'));
      await tester.scrollUntilVisible(panel, 160,
          scrollable: find.byKey(const Key('dispatcher-cabinet')));
      expect(panel, findsOneWidget);
      await tester.tap(find.descendant(
          of: panel, matching: find.byType(ExpansionTile)));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }
    for (var i = 0; i < 3; i++) {
      expect(store.archivedChats[i].pilotMessages, ['Пилот номер $i']);
      expect(store.archivedChats[i].passengerMessages, ['Ответ номер $i']);
    }
  });

  testWidgets('Decline returns request to dispatcher for reassignment',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Аэропорт Вильнюса',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    ), isTrue);
    await tester.pumpWidget(MaterialApp(
      home: DemoDispatcherCabinet(tripStore: store),
    ));
    await tester.tap(find.byKey(const Key('dispatcher-assign-pilot')));
    await tester.pump();
    expect(store.declineAssignedPilot(), isTrue);
    await tester.pump();
    expect(store.status, DemoTripStatus.requested);
    expect(find.byKey(const Key('dispatcher-assign-pilot')), findsOneWidget);
    expect(store.advancePilot(), isFalse);
  });
}
