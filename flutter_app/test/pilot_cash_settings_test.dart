import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/pilot_payment_settings.dart';
import 'package:private_drive/demo_interfaces.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // Historical cash orders remain usable after disabling NEW cash orders.
  DemoTripStore cashOrder() {
    final source = DemoTripStore();
    expect(source.create(
      from: 'Вильнюс', to: 'Аэропорт Вильнюса',
      departure: DateTime.now(),
      paymentMethod: 'Карта', services: const []), isTrue);
    final saved = jsonDecode(source.toPersistedJson()!)
        as Map<String, dynamic>;
    source.dispose();
    saved['paymentMethod'] = 'Наличные';
    final store = DemoTripStore();
    expect(store.restorePersistedJson(jsonEncode(saved)), isTrue);
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
    // The drawer is scrollable: new pilot-only menu entries can move
    // payment settings below the initial viewport without hiding the feature.
    final cashItem = find.byKey(const Key('pilot-drawer-cash-settings'));
    await tester.scrollUntilVisible(
      cashItem,
      120,
      scrollable: find.descendant(
        of: find.byKey(const Key('pilot-navigation-drawer')),
        matching: find.byType(Scrollable),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(cashItem);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pilot-accept-cash')), findsOneWidget);
    final toggle = find.byKey(const Key('pilot-accept-cash'));
    expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
    await tester.tap(toggle);
    await tester.pump();
    expect(store.pilotAcceptsCash, isTrue);
    expect(store.assignPilot(), isTrue);
    expect(PilotPaymentSettings.instance.acceptCash, isTrue);
    await tester.tap(toggle);
    await tester.pump();
    expect(PilotPaymentSettings.instance.acceptCash, isFalse);
    expect(store.pilotAcceptsCash, isFalse);
    expect(store.acceptAssignedPilot(), isFalse);
  });
}
