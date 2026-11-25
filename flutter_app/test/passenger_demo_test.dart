import 'package:private_drive/remote_sync_demo.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/passenger_demo.dart';

void main() {
  testWidgets('QA booking opens the dispatcher submission', (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(home: PassengerDemo(
      enableMapTiles: false, tripStore: store,
    )));
    final form = find.descendant(of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable)).first;
    final preset = find.byKey(const Key('route-kaunas'));
    await tester.scrollUntilVisible(preset, 150, scrollable: form);
    tester.widget<ActionChip>(preset).onPressed!();
    await tester.pump();
    final submit = find.byKey(const Key('passenger-book-disabled'));
    await tester.scrollUntilVisible(submit, 160, scrollable: form);
    tester.widget<FilledButton>(submit).onPressed!();
    await tester.pumpAndSettle();
    final booking = tester.widget<RemoteSyncDemo>(find.byType(RemoteSyncDemo));
    expect(booking.stagingDispatcher, isTrue);
    expect(booking.initialFrom, 'Вильнюс');
    expect(booking.initialTo, 'Каунас');
    expect(store.trip, isNull);
  }, skip: !const bool.fromEnvironment('PD_QA_SERVER_BOOKING'));

  testWidgets('English airport alias suggests a selectable offline address',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    final form = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-to')), 180, scrollable: form);
    await tester.enterText(find.byKey(const Key('passenger-to')),
      'Vilnius Airport');
    await tester.pump();
    expect(find.text('Аэропорт Вильнюса'), findsOneWidget);
    expect(find.byKey(const Key('passenger-address-search-error')),
      findsNothing);
    await tester.tap(find.byKey(const Key('passenger-to-suggestion-0')));
    await tester.pump();
    expect(tester.widget<TextField>(
      find.byKey(const Key('passenger-to'))).controller!.text,
      'Аэропорт Вильнюса');
  });

  testWidgets('Passenger presets, address swap and date/time controls are local',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);

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
      find.byKey(const Key('passenger-to')),
      -160,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );

    expect(
      tester.widget<TextField>(find.byKey(const Key('passenger-from')))
          .controller!.text,
      'Вильнюс',
    );
    expect(
      tester.widget<TextField>(find.byKey(const Key('passenger-to')))
          .controller!.text,
      'Каунас',
    );

    await tester.ensureVisible(find.byKey(const Key('passenger-swap')));
    await tester.tap(find.byKey(const Key('passenger-swap')));
    await tester.pump();
    // Scroll upward: ListView may dispose the A field after tapping swap.
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-from')),
      -180,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(
      tester.widget<TextField>(find.byKey(const Key('passenger-from')))
          .controller!.text,
      'Каунас',
    );
    expect(
      tester.widget<TextField>(find.byKey(const Key('passenger-to')))
          .controller!.text,
      'Вильнюс',
    );

    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-date')), -160,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(
      tester.widget<OutlinedButton>(find.byKey(const Key('passenger-date')))
          .onPressed,
      isNotNull,
    );
    expect(
      tester.widget<OutlinedButton>(find.byKey(const Key('passenger-time')))
          .onPressed,
      isNotNull,
    );
    expect(find.text('Диспетчер'), findsNothing);
    expect(find.text('К пассажиру'), findsNothing);
  });

  testWidgets('Fixed route price changes only with priced services',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
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
      find.byKey(const Key('passenger-price-preview')), 220,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(find.text('Предварительная стоимость: 110 €'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.byKey(const Key('service-meet-sign')), -180,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.pumpAndSettle();
    // Exercise the checkbox callback directly: the expandable preferences
    // panel may move this tile under the viewport while scrolling.
    tester.widget<CheckboxListTile>(
      find.byKey(const Key('service-meet-sign')),
    ).onChanged!(true);
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')), 220,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(find.text('Предварительная стоимость: 125 €'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.byKey(const Key('service-pets')), -180,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    // The expanded preferences panel may position this tile off-screen.
    // Invoke its callback directly to test the price state deterministically.
    tester.widget<CheckboxListTile>(
      find.byKey(const Key('service-pets')),
    ).onChanged!(true);
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')), 220,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(find.text('Расчётная часть: 125 € · дополнительные услуги по запросу'),
        findsOneWidget);
    expect(find.text('Предварительная стоимость: 125 €'), findsNothing);
  });

  testWidgets('Approved Vilnius–Kaunas return transfer costs 200 EUR',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    final list = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('route-kaunas')), 160, scrollable: list);
    tester.widget<ActionChip>(find.byKey(const Key('route-kaunas')))
        .onPressed!();
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-round-trip')), -100, scrollable: list);
    tester.widget<SwitchListTile>(find.byKey(const Key('passenger-round-trip')))
        .onChanged!(true);
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')), 220, scrollable: list);
    expect(find.text('Предварительная стоимость: 200 €'), findsOneWidget);
    expect(find.text('Предварительная стоимость: 190 €'), findsNothing);
  });

  testWidgets('Sober driver doubles the base fare and meet sign adds 15 EUR',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    final list = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('route-kaunas')), 160, scrollable: list);
    tester.widget<ActionChip>(find.byKey(const Key('route-kaunas')))
        .onPressed!();
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('service-sober')), 180, scrollable: list);
    tester.widget<CheckboxListTile>(find.byKey(const Key('service-sober')))
        .onChanged!(true);
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')), 220, scrollable: list);
    expect(find.text('Предварительная стоимость: 220 €'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.byKey(const Key('service-meet-sign')), -180, scrollable: list);
    tester.widget<CheckboxListTile>(find.byKey(const Key('service-meet-sign')))
        .onChanged!(true);
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')), 220, scrollable: list);
    expect(find.text('Предварительная стоимость: 235 €'), findsOneWidget);
  });

  testWidgets('Unpriced coffee keeps approved amount visible, not final',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    final list = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.byKey(const Key('route-airport')), 160, scrollable: list);
    tester.widget<ActionChip>(find.byKey(const Key('route-airport')))
        .onPressed!();
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('service-coffee')), 180, scrollable: list);
    tester.widget<CheckboxListTile>(find.byKey(const Key('service-coffee')))
        .onChanged!(true);
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')), 220, scrollable: list);
    expect(find.text('Расчётная часть: 40 € · дополнительные услуги по запросу'),
        findsOneWidget);
    expect(find.text('Предварительная стоимость: 40 €'), findsNothing);
  });

  testWidgets('Changing route clears old fixed transfer fare',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    final list = find.descendant(
      of: find.byKey(const Key('passenger-form')),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(find.byKey(const Key('route-kaunas')),
        160, scrollable: list);
    // The chip can be partially covered by the scrolling viewport in tests.
    tester.widget<ActionChip>(find.byKey(const Key('route-kaunas')))
        .onPressed!();
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-price-preview')),
      220, scrollable: list);
    expect(find.text('Предварительная стоимость: 110 €'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-to')), -200, scrollable: list);
    await tester.enterText(find.byKey(const Key('passenger-to')), 'Тракай');
    await tester.pump();
    expect(find.text('Предварительная стоимость: 110 €'), findsNothing);
    expect(find.textContaining('Стоимость по запросу'), findsNothing);
  });

  testWidgets('Services and payment change preview, never create a booking',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    await tester.scrollUntilVisible(
      find.byKey(const Key('service-meet-sign')),
      220,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    tester.widget<CheckboxListTile>(
      find.byKey(const Key('service-meet-sign')),
    ).onChanged!(true);
    await tester.pump();
    expect(
      tester.widget<CheckboxListTile>(find.byKey(const Key('service-meet-sign')))
          .value,
      isTrue,
    );

    await tester.scrollUntilVisible(
      find.byKey(const Key('payment-PayPal')),
      -220,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    await tester.tap(find.byKey(const Key('payment-PayPal')));
    await tester.pump();
    expect(
      tester.widget<ChoiceChip>(find.byKey(const Key('payment-PayPal')))
          .selected,
      isTrue,
    );
    expect(find.textContaining('PayPal'), findsWidgets);
    expect(find.byKey(const Key('payment-Наличные')), findsNothing);

    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-book-disabled')),
      220,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ).first,
    );
    expect(
      tester.widget<FilledButton>(find.byKey(const Key('passenger-book-disabled')))
          .onPressed,
      isNull,
    );
  });
}
