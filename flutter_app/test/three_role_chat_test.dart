import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_dispatcher_cabinet.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_orders_demo.dart';

void main() {
  test('Dispatcher and passenger chat persists and archives by order', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(from: 'Vilnius', to: 'Kaunas',
      paymentMethod: 'PayPal', departure: DateTime(2026, 11, 20),
      services: const []), isTrue);
    expect(store.addPassengerChatMessage('Когда приедет водитель?'), isTrue);
    expect(store.addDispatcherChatMessage('Подбираем пилота'), isTrue);
    expect(store.dispatcherChatMessages, ['Подбираем пилота']);

    final saved = store.toPersistedJson()!;
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(saved), isTrue);
    expect(restored.dispatcherChatMessages, ['Подбираем пилота']);
    expect(restored.passengerChatMessages, ['Когда приедет водитель?']);

    expect(store.cancelByPassenger(), isTrue);
    expect(store.create(from: 'Kaunas', to: 'Vilnius',
      paymentMethod: 'PayPal', departure: DateTime(2026, 11, 21),
      services: const []), isTrue);
    expect(store.dispatcherChatMessages, isEmpty);
    expect(store.archivedChats.last.dispatcherMessages, ['Подбираем пилота']);
    final afterRestart = DemoTripStore();
    addTearDown(afterRestart.dispose);
    expect(afterRestart.restorePersistedJson(store.toPersistedJson()!), isTrue);
    expect(afterRestart.archivedChats.last.dispatcherMessages,
      ['Подбираем пилота']);

    final old = jsonDecode(saved) as Map<String, dynamic>;
    old.remove('dispatcherChatMessages');
    final legacy = DemoTripStore();
    addTearDown(legacy.dispose);
    expect(legacy.restorePersistedJson(jsonEncode(old)), isTrue);
    expect(legacy.dispatcherChatMessages, isEmpty);
  });

  testWidgets('Dispatcher sends message visible in passenger order chat',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'Карта', departure: DateTime(2026, 11, 20),
      services: const []), isTrue);
    await tester.pumpWidget(MaterialApp(home: DemoDispatcherCabinet(
      tripStore: store, enableMapTiles: false, initialTab: 0,
    )));
    await tester.ensureVisible(find.byKey(const Key('dispatcher-current-chat')));
    await tester.tap(find.text('Переписка по текущему заказу'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('dispatcher-chat-input')),
      'Водитель будет назначен');
    await tester.tap(find.byKey(const Key('dispatcher-chat-send')));
    await tester.pump();
    expect(store.dispatcherChatMessages, ['Водитель будет назначен']);
    await tester.pumpWidget(MaterialApp(home: PassengerOrdersDemo(
      tripStore: store,
    )));
    await tester.pumpAndSettle();
    expect(find.text('Диспетчер: Водитель будет назначен'), findsOneWidget);
    expect(find.byKey(const Key('passenger-chat-input')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('passenger-chat-input')),
      'Спасибо');
    await tester.tap(find.byKey(const Key('passenger-chat-send')));
    await tester.pump();
    expect(store.passengerChatMessages, ['Спасибо']);
  });
}
