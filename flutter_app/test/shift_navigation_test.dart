import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/demo_trip_store.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  testWidgets('Leaving pilot cabin keeps online shift visible to dispatcher',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: PrivateDriveDemo(enableMapTiles: false)),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('open-pilot-preview')));
    await tester.tap(find.byKey(const Key('open-pilot-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-power-toggle')), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-power-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.byKey(const Key('pilot-enable-gps')), findsNothing);
    expect(find.byKey(const Key('pilot-disable-gps')), findsNothing);

    await tester.tap(find.byKey(const Key('exit-pilot-preview')));
    await tester.pumpAndSettle();
    expect(find.text('На линии · демо'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const Key('open-dispatcher-preview')));
    await tester.tap(find.byKey(const Key('open-dispatcher-preview')));
    await tester.pumpAndSettle();
    // Opening a different role menu and returning from Android pause must
    // never switch the pilot offline or discard an existing GPS fix.
    tester.binding.handleAppLifecycleStateChanged(
      AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(
      AppLifecycleState.resumed);
    await tester.pump();
    await tester.tap(find.byKey(const Key('dispatcher-open-drawer')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('dispatcher-menu-2')));
    await tester.pumpAndSettle();
    expect(find.textContaining('На линии'), findsWidgets);

    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('open-pilot-preview')));
    await tester.tap(find.byKey(const Key('open-pilot-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
  });

  test('Trip mode is retained in dispatcher assignment; return tariff is data',
      () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'PayPal',
      departure: DateTime(2026, 11, 18),
      services: const [],
      rideType: 'Трансфер',
      roundTrip: true,
    ), isTrue);
    expect(store.trip!.rideType, 'Трансфер');
    expect(store.trip!.roundTrip, isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.trip!.roundTrip, isTrue);
  });
}
