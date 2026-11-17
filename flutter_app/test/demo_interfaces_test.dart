import 'dart:async';

import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/main.dart';

void main() {
  testWidgets('Offline entry opens passenger preview; booking stays disabled',
      (tester) async {
    expect(apiBaseUrl, isEmpty);
    await tester.pumpWidget(const PrivateDriveApp());
    // ListView lazily builds off-screen children: scroll until the demo entry
    // is in the widget tree before attempting to tap it.
    await tester.scrollUntilVisible(
      find.byKey(const Key('open-offline-demo')),
      220,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('open-offline-demo')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('open-passenger-preview')));
    await tester.pumpAndSettle();

    expect(find.byType(PassengerDemo), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-to')),
      200,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ),
    );
    expect(find.text('Откуда'), findsOneWidget);
    expect(find.text('Куда'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('passenger-book-disabled')),
      250,
      scrollable: find.descendant(
        of: find.byKey(const Key('passenger-form')),
        matching: find.byType(Scrollable),
      ),
    );
    expect(find.textContaining('Заказать поездку — недоступно'), findsOneWidget);
    final booking = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Заказать поездку — недоступно в демоверсии'),
    );
    expect(booking.onPressed, isNull);
    expect(find.byType(PilotDemo), findsNothing);
  });

  testWidgets('Pilot gets only full-screen map surface and local trip controls',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: PilotDemo(enableMapTiles: false)));
    expect(find.byKey(const Key('pilot-map-surface')), findsOneWidget);
    expect(find.text('GPS выключен'), findsOneWidget);
    expect(find.text('Нет активной поездки'), findsOneWidget);
    expect(find.text('К пассажиру'), findsOneWidget);
    expect(find.text('Откуда'), findsNothing);
    expect(find.text('Куда'), findsNothing);
    expect(find.textContaining('Заказать поездку'), findsNothing);
    expect(find.byType(Drawer), findsNothing);
    expect(find.byType(BottomNavigationBar), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.text('Администратор'), findsNothing);
    expect(find.text('Диспетчер'), findsNothing);

    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.text('Едем к пассажиру'), findsOneWidget);
    expect(find.text('В путь'), findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-pause-trip')));
    await tester.pump();
    expect(find.text('Остановка · демо'), findsOneWidget);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('pilot-next-trip')),
    ).onPressed, isNull);

    await tester.tap(find.byKey(const Key('pilot-pause-trip')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.text('Поездка выполняется'), findsOneWidget);
    await tester.tap(find.byKey(const Key('pilot-next-trip')));
    await tester.pump();
    expect(find.text('Нет активной поездки'), findsOneWidget);
  });
  testWidgets('Pilot GPS stream updates map state locally and can be disabled',
      (tester) async {
    final controller = StreamController<LatLng>.broadcast(sync: true);
    addTearDown(controller.close);
    await tester.pumpWidget(MaterialApp(
      home: PilotDemo(enableMapTiles: false, positions: controller.stream),
    ));
    expect(find.byKey(const Key('pilot-enable-gps')), findsOneWidget);
    expect(find.byKey(const Key('pilot-disable-gps')), findsNothing);

    await tester.tap(find.byKey(const Key('pilot-enable-gps')));
    await tester.pump();
    expect(find.byKey(const Key('pilot-enable-gps')), findsNothing);
    expect(find.byKey(const Key('pilot-disable-gps')), findsOneWidget);

    controller.add(const LatLng(54.6872, 25.2797));
    await tester.pump();
    expect(find.text('GPS активен · только на устройстве'), findsOneWidget);
    expect(find.byKey(const Key('pilot-center-map')), findsOneWidget);

    await tester.tap(find.byKey(const Key('pilot-disable-gps')));
    await tester.pump();
    expect(find.text('GPS выключен'), findsOneWidget);
    expect(find.byKey(const Key('pilot-enable-gps')), findsOneWidget);
    expect(find.byKey(const Key('pilot-disable-gps')), findsNothing);
    expect(find.byKey(const Key('pilot-center-map')), findsNothing);
    expect(find.text('Администратор'), findsNothing);
    expect(find.text('Диспетчер'), findsNothing);
  });

}
