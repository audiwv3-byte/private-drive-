import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/passenger_demo.dart';

void main() {
  testWidgets('Passenger presets, address swap and date/time controls are local',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
    expect(find.byKey(const Key('route-kaunas')), findsOneWidget);

    await tester.tap(find.byKey(const Key('route-kaunas')));
    await tester.pump();
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

    await tester.ensureVisible(find.byKey(const Key('passenger-date')));
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

  testWidgets('Services and payment change preview, never create a booking',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: PassengerDemo(enableMapTiles: false),
    ));
    await tester.scrollUntilVisible(
      find.byKey(const Key('service-meet-sign')),
      220,
      scrollable: find.byKey(const Key('passenger-form')),
    );
    await tester.tap(find.byKey(const Key('service-meet-sign')));
    await tester.pump();
    expect(
      tester.widget<CheckboxListTile>(find.byKey(const Key('service-meet-sign')))
          .value,
      isTrue,
    );

    await tester.scrollUntilVisible(
      find.byKey(const Key('payment-PayPal')),
      220,
      scrollable: find.byKey(const Key('passenger-form')),
    );
    await tester.tap(find.byKey(const Key('payment-PayPal')));
    await tester.pump();
    expect(
      tester.widget<ChoiceChip>(find.byKey(const Key('payment-PayPal')))
          .selected,
      isTrue,
    );
    expect(find.textContaining('PayPal'), findsWidgets);
    expect(find.text('Наличные'), findsNothing);

    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-book-disabled')),
      220,
      scrollable: find.byKey(const Key('passenger-form')),
    );
    expect(
      tester.widget<FilledButton>(find.byKey(const Key('passenger-book-disabled')))
          .onPressed,
      isNull,
    );
  });
}
