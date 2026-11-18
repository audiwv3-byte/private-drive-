import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_dispatcher_cabinet.dart';
import 'package:private_drive/demo_rating_panel.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/company_info.dart';

void main() {
  test('Pilot GPS is session-local and cleared offline', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    store.updatePilotLocation(54.68, 25.28);
    expect(store.pilotLatitude, isNull, reason: 'No GPS while offline');
    store.setPilotOnline(true);
    store.updatePilotLocation(54.68, 25.28);
    expect(store.pilotLatitude, 54.68);
    expect(store.pilotLongitude, 25.28);
    expect(store.pilotLastSeen, isNotNull);
    store.updatePilotLocation(999, 25);
    expect(store.pilotLatitude, 54.68);
    store.setPilotOnline(false);
    expect(store.pilotLatitude, isNull);
    expect(store.pilotLongitude, isNull);
    expect(store.pilotLastSeen, isNull);
  });

  test('Ratings require completion, both scores and exactly one submission', () {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.rateFinishedTrip(tripStars: 5, serviceStars: 5), isFalse);
    expect(store.create(
      from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'Карта', departure: DateTime(2026, 11, 18),
      services: const [],
    ), isTrue);
    expect(store.rateFinishedTrip(tripStars: 5, serviceStars: 5), isFalse);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.status, DemoTripStatus.finished);
    expect(store.rateFinishedTrip(tripStars: 0, serviceStars: 5), isFalse);
    expect(store.rateFinishedTrip(tripStars: 5, serviceStars: 6), isFalse);
    expect(store.rateFinishedTrip(tripStars: 4, serviceStars: 5), isTrue);
    expect(store.tripRating, 4);
    expect(store.serviceRating, 5);
    expect(store.rateFinishedTrip(tripStars: 1, serviceStars: 1), isFalse);
    expect(store.create(
      from: 'Каунас', to: 'Вильнюс',
      paymentMethod: 'PayPal', departure: DateTime(2026, 11, 19),
      services: const [],
    ), isTrue);
    expect(store.tripRating, isNull);
    expect(store.serviceRating, isNull);
  });

  testWidgets('Dispatcher has separate map, pilots and passengers tabs',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: DemoDispatcherCabinet(tripStore: store, enableMapTiles: false),
    ));
    expect(find.byKey(const Key('dispatcher-cabinet')), findsOneWidget);
    await tester.tap(find.byKey(const Key('dispatcher-tab-1')));
    await tester.pump();
    expect(find.byKey(const Key('dispatcher-map-tab')), findsOneWidget);
    expect(find.textContaining('Подтверждённых GPS-точек нет'), findsOneWidget);

    await tester.tap(find.byKey(const Key('dispatcher-tab-2')));
    await tester.pump();
    expect(find.byKey(const Key('dispatcher-pilots-tab')), findsOneWidget);
    expect(find.textContaining('Не на линии'), findsOneWidget);

    await tester.tap(find.byKey(const Key('dispatcher-tab-3')));
    await tester.pump();
    expect(find.byKey(const Key('dispatcher-passengers-tab')), findsOneWidget);
    expect(find.textContaining('отсутствуют'), findsOneWidget);
  });

  testWidgets('Passenger rates journey and service after trip finishes',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.create(from: 'Вильнюс', to: 'Каунас',
      paymentMethod: 'PayPal', departure: DateTime(2026, 11, 18),
      services: const []), isTrue);
    expect(store.assignPilot(), isTrue);
    expect(store.acceptAssignedPilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    expect(store.advancePilot(), isTrue);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: DemoRatingPanel(tripStore: store)),
    ));
    expect(find.byKey(const Key('passenger-rating-panel')), findsOneWidget);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('passenger-submit-rating'))).onPressed, isNull);
    await tester.tap(find.byKey(const Key('rate-trip-4')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('rate-service-5')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('passenger-submit-rating')));
    await tester.pump();
    expect(store.tripRating, 4);
    expect(store.serviceRating, 5);
    expect(find.byKey(const Key('passenger-rating-complete')), findsOneWidget);
  });

  testWidgets('Company page exposes confirmed contacts and draft policies',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: CompanyInfoPage()));
    expect(find.byKey(const Key('company-email')), findsOneWidget);
    expect(find.byKey(const Key('company-telegram-support')), findsOneWidget);
    expect(find.byKey(const Key('company-telegram-channel')), findsOneWidget);
    await tester.tap(find.text('Соглашение'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('company-terms-tab')), findsOneWidget);
    expect(find.textContaining('не является окончательной'), findsWidgets);
    await tester.tap(find.text('Конфиденциальность'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('company-privacy-tab')), findsOneWidget);
  });
}
