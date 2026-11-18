import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
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

  testWidgets('Passenger and pilot share exactly one offline demo trip',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PrivateDriveDemo(enableMapTiles: false),
    ));
    expect(find.text('Нет тестового заказа'), findsOneWidget);

    await tester.tap(find.byKey(const Key('open-passenger-preview')));
    await tester.pumpAndSettle();
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
    await tester.tap(find.byKey(const Key('demo-dispatch-assign')));
    await tester.pump();
    expect(find.text('Пилот назначен · ожидает выезда'), findsOneWidget);

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
    expect(find.text('К пассажиру'), findsOneWidget);

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
