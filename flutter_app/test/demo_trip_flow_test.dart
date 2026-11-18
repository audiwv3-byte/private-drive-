import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  testWidgets('Pickup map shows a city-centre hint, never an invented address',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(
        enableMapTiles: true,
        loadMapTiles: false,
        tripStore: store,
      ),
    ));
    expect(find.byKey(const Key('pilot-pickup-preview-pin')), findsNothing);
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(store.status, DemoTripStatus.approaching);
    expect(find.byKey(const Key('pilot-pickup-preview-pin')), findsOneWidget);
    expect(find.text('Подача: Вильнюс'), findsOneWidget);
    expect(find.textContaining('точный адрес подачи не указан'), findsOneWidget);
  });

  testWidgets('Unknown pickup address shows warning, no fictitious marker',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Пример улицы 123', to: 'Каунас',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(
        enableMapTiles: true,
        loadMapTiles: false,
        tripStore: store,
      ),
    ));
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-pickup-preview-pin')), findsNothing);
    expect(find.textContaining('требуется геокодирование адреса'), findsOneWidget);
  });

  test('Local trip state transitions require explicit assignment and valid route', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.advancePilot(), isFalse);
    expect(store.assignPilot(), isFalse);
    expect(
      store.create(
        from: 'Вильнюс',
        to: 'Вильнюс',
        paymentMethod: 'Карта',
        departure: DateTime(2026, 11, 18),
        services: const [],
      ),
      isFalse,
    );
    expect(store.status, isNull);
    expect(store.create(
      from: 'Вильнюс',
      to: 'Каунас',
      paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 18, 12),
      services: const ['Музыка в дорогу'],
    ), isTrue);
    expect(store.status, DemoTripStatus.requested);
    expect(store.advancePilot(), isFalse);
    expect(store.create(
      from: 'Вильнюс',
      to: 'Варшава',
      paymentMethod: 'Карта',
      departure: DateTime(2026, 11, 18),
      services: const [],
    ), isFalse);
    expect(store.assignPilot(), isTrue);
    expect(store.assignPilot(), isFalse);
    expect(store.advancePilot(), isFalse);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isFalse);
    expect(store.advancePilot(), isTrue);
    expect(store.status, DemoTripStatus.approaching);
    expect(store.togglePause(), isTrue);
    expect(store.advancePilot(), isFalse);
    expect(store.togglePause(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.status, DemoTripStatus.underway);
    expect(store.advancePilot(), isTrue);
    expect(store.status, DemoTripStatus.finished);
    expect(store.advancePilot(), isFalse);
    expect(store.trip!.paymentMethod, 'PayPal');
    expect(store.trip!.services, contains('Музыка в дорогу'));
  });

  testWidgets('Pilot can decline assigned order and dispatcher can reassign',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс',
      to: 'Аэропорт Вильнюса',
      paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 18, 14),
      services: const [],
    ), isTrue);
    expect(store.assignPilot(), isTrue);

    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, tripStore: store),
    ));
    expect(find.byKey(const Key('pilot-assigned-offer')), findsOneWidget);
    expect(find.text('Вильнюс → Аэропорт Вильнюса'), findsOneWidget);
    expect(find.byKey(const Key('pilot-passenger-chat')), findsNothing);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('pilot-next-trip')),
    ).onPressed, isNull);

    await tester.tap(find.byKey(const Key('pilot-decline-assigned')));
    await tester.pump();
    expect(store.status, DemoTripStatus.requested);
    expect(store.pilotAccepted, isFalse);
    expect(find.byKey(const Key('pilot-assigned-offer')), findsNothing);
    expect(store.advancePilot(), isFalse);
    expect(store.assignPilot(), isTrue);
    await tester.pump();
    expect(find.byKey(const Key('pilot-assigned-offer')), findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-accept-assigned')));
    await tester.pump();
    expect(store.pilotAccepted, isTrue);
    expect(store.status, DemoTripStatus.assigned);
    expect(find.byKey(const Key('pilot-assigned-offer')), findsNothing);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('pilot-next-trip')),
    ).onPressed, isNotNull);
  });

  testWidgets('Passenger and pilot share exactly one offline demo trip',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PrivateDriveDemo(enableMapTiles: false),
    ));
    expect(find.text('Нет тестового заказа'), findsOneWidget);

    await tester.tap(find.byKey(const Key('open-passenger-preview')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('route-kaunas')),
      160,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('route-kaunas')));
    await tester.pump();

    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-book-disabled')),
      240,
      scrollable: find.byType(Scrollable).first,
    );
    final book = find.byKey(const Key('passenger-book-disabled'));
    expect(tester.widget<FilledButton>(book).onPressed, isNotNull);
    await tester.tap(book);
    await tester.pump();
    expect(find.text('Заявка создана · ожидает назначения'), findsOneWidget);
    expect(tester.widget<FilledButton>(book).onPressed, isNull);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Заявка создана · ожидает назначения'), findsOneWidget);
    expect(find.text('Вильнюс → Каунас'), findsOneWidget);
    expect(find.byKey(const Key('demo-dispatch-assign')), findsNothing);
    await tester.tap(find.byKey(const Key('open-dispatcher-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('dispatcher-cabinet')), findsOneWidget);
    expect(find.byKey(const Key('dispatcher-order-card')), findsOneWidget);
    await tester.tap(find.byKey(const Key('dispatcher-assign-pilot')));
    await tester.pump();
    expect(find.text('Пилот назначен · ожидает принятия'), findsWidgets);
    expect(find.byKey(const Key('dispatcher-assign-pilot')), findsNothing);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const Key('open-pilot-preview')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('open-pilot-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-power-toggle')), findsOneWidget);
    expect(find.byKey(const Key('pilot-map-surface')), findsNothing);
    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.byKey(const Key('pilot-power-toggle')), findsNothing);
    expect(find.text('Диспетчер'), findsNothing);
    expect(find.text('Откуда'), findsNothing);
    expect(find.byKey(const Key('pilot-global-offer')), findsOneWidget);
    expect(find.byKey(const Key('pilot-global-route')), findsOneWidget);
    expect(find.byKey(const Key('pilot-assigned-offer')), findsNothing);
    expect(find.text('К пассажиру'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('pilot-next-trip'))).onPressed, isNull);
    await tester.tap(find.byKey(const Key('pilot-global-accept')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-global-offer')), findsNothing);

    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.text('Пилот едет к пассажиру'), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-pause-trip')));
    await tester.pump();
    expect(find.text('Остановка · демо'), findsOneWidget);
    expect(
      tester.widget<FilledButton>(find.byKey(const Key('pilot-next-trip')))
          .onPressed,
      isNull,
    );
    await tester.tap(find.byKey(const Key('pilot-pause-trip')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.text('Поездка выполняется'), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.text('Поездка завершена · демо'), findsOneWidget);

    await tester.tap(find.byKey(const Key('exit-pilot-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-power-toggle')), findsOneWidget);
    expect(find.text('На линии · демо'), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pump();
    expect(find.text('Не на линии · демо'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Поездка завершена · демо'), findsOneWidget);
    await tester.tap(find.byKey(const Key('open-passenger-preview')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-trip-status')),
      240,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Поездка завершена · демо'), findsOneWidget);
    expect(find.text('Наличные'), findsNothing);
  });
}
