import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/pilot_cabin.dart';

void main() {
  testWidgets('Leaving pilot cabin does not turn off pilot shift or clear GPS',
      (tester) async {
    final trip = DemoTripStore();
    addTearDown(trip.dispose);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: Builder(builder: (context) => FilledButton(
        key: const Key('enter-cabin'),
        onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => PilotCabin(enableMapTiles: false, tripStore: trip),
        )),
        child: const Text('Пилот'),
      ))),
    ));
    await tester.tap(find.byKey(const Key('enter-cabin')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-power-toggle')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pumpAndSettle();
    expect(trip.pilotOnline, isTrue);
    trip.updatePilotLocation(54.6872, 25.2797);
    await tester.pump();
    expect(trip.pilotLatitude, 54.6872);
    await tester.tap(find.byKey(const Key('exit-pilot-preview')));
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('enter-cabin')), findsOneWidget);
    expect(trip.pilotOnline, isTrue,
      reason: 'Back navigation must not be interpreted as going offline.');
    expect(trip.pilotLatitude, 54.6872,
      reason: 'The last GPS fix should survive navigating to dispatcher.');
    await tester.tap(find.byKey(const Key('enter-cabin')));
    await tester.pumpAndSettle();
    expect(find.byType(PilotDemo), findsOneWidget,
      reason: 'Reopening an active shift should return to pilot map.');
    expect(trip.pilotOnline, isTrue);
  });

  test('Trip types are preserved independently of passenger payment method', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс',
      to: 'Каунас',
      paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 18),
      services: const [],
      rideType: 'Трансфер',
      roundTrip: true,
    ), isTrue);
    expect(store.trip!.rideType, 'Трансфер');
    expect(store.trip!.roundTrip, isTrue);
    expect(store.trip!.paymentMethod, 'PayPal');
  });
}
