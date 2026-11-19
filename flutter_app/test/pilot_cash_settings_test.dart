import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/pilot_payment_settings.dart';
import 'package:private_drive/demo_interfaces.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  DemoTripStore cashOrder() {
    final store = DemoTripStore();
    expect(store.create(
      from: 'Вильнюс', to: 'Аэропорт Вильнюса',
      departure: DateTime(2026, 11, 21),
      paymentMethod: 'Наличные', services: const []), isTrue);
    return store;
  }

  test('Cash ride is allowed but not assigned to opted-out pilot', () {
    final store = cashOrder();
    addTearDown(store.dispose);
    expect(store.pilotAcceptsCash, isFalse);
    expect(store.cashOrderNeedsOtherPilot, isTrue);
    expect(store.assignPilot(), isFalse);
    store.setPilotAcceptsCash(true);
    expect(store.assignPilot(), isTrue);
    store.setPilotAcceptsCash(false);
    expect(store.acceptAssignedPilot(), isFalse);
    store.setPilotAcceptsCash(true);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.trip!.paymentMethod, 'Наличные');
  });

  testWidgets('Pilot can disable or enable cash from left menu',
      (tester) async {
    final store = cashOrder();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, tripStore: store)));
    await tester.tap(find.byKey(const Key('pilot-open-drawer')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('pilot-drawer-cash-settings')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-accept-cash')), findsOneWidget);
    final toggle = find.byKey(const Key('pilot-accept-cash'));
    expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
    await tester.tap(toggle);
    await tester.pump();
    expect(store.pilotAcceptsCash, isTrue);
    expect(store.assignPilot(), isTrue);
    expect(await SharedPreferencesAsync().getBool(
      PilotPaymentSettings.cashKey), isTrue);
    await tester.tap(toggle);
    await tester.pump();
    expect(store.pilotAcceptsCash, isFalse);
    expect(store.acceptAssignedPilot(), isFalse);
  });
}
