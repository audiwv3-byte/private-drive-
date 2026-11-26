import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../lib/main.dart' as app;
import '../lib/native_pilot_orders.dart';
import '../lib/pd_http_api.dart';
import '../lib/qa_pilot_gps.dart';

const orderId = '05cdbc84-0930-4c52-baa1-149a03190d78';
const sessionToken = 'qa39-synthetic-session-for-isolated-tests-only';
const origin = 'https://qa.invalid';

class AssignedOrderApi extends NativePilotOrdersApi {
  AssignedOrderApi() : super(baseUrl: origin, token: sessionToken);
  int reads = 0;

  @override
  Future<List<PilotAssignedOrder>> load() async {
    reads++;
    return const [PilotAssignedOrder(orderId: orderId, origin: 'A',
        destination: 'B', date: '2027-01-01', time: '12:00', status: 'assigned')];
  }
}

void main() {
  for (final platform in [TargetPlatform.android, TargetPlatform.iOS]) {
    testWidgets('$platform decline GPS in the assigned trip', (tester) async {
      debugDefaultTargetPlatformOverride = platform;
      try {
        final api = AssignedOrderApi();
        await tester.pumpWidget(MaterialApp(home: Scaffold(body:
            SingleChildScrollView(child: PilotAssignedOrdersPanel(api: api)))));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Передавать GPS диспетчеру'));
        await tester.pumpAndSettle();
        expect(find.text('Разрешить GPS'), findsOneWidget);
        await tester.tap(find.text('Отмена'));
        await tester.pumpAndSettle();
        expect(find.text('Передавать GPS диспетчеру'), findsOneWidget);
        expect(find.text('Остановить передачу GPS'), findsNothing);
        expect(api.reads, 1);
        await tester.pumpWidget(const SizedBox());
      } finally {
        debugDefaultTargetPlatformOverride = null;
      }
    });
  }

  test('one HTTPS origin and valid session before any GPS request', () async {
    expect(app.apiBaseUrl, origin);
    expect(PdHttpApi.configuredOrigin, origin);
    final transport = MockClient((_) async => fail('unexpected HTTP request'));
    for (final base in ['', 'http://qa.invalid', 'https://other.invalid',
        'https://qa.invalid:8080', 'https://user@qa.invalid',
        'https://qa.invalid/path', 'https://qa.invalid?x', 'https://qa.invalid/#x']) {
      final api = NativePilotOrdersApi(baseUrl: base, token: sessionToken, client: transport);
      expect(api.gpsEnabled, false);
      await expectLater(api.publishGps(orderId, null, 101), throwsFormatException);
    }
    final api = NativePilotOrdersApi(baseUrl: origin, token: '', client: transport);
    await expectLater(api.publishGps(orderId, null, 101),
        throwsA(isA<PdHttpStatusException>().having((e) => e.statusCode, 'status', 401)));
  });

  test('consent and assignment before first fix, opt out after final fix', () async {
    final bodies = <Map<String, dynamic>>[];
    final api = NativePilotOrdersApi(baseUrl: origin, token: sessionToken,
        client: MockClient((req) async {
          expect(req.url.toString(), '$origin/native-pilot-orders/$orderId/gps');
          expect(req.followRedirects, false);
          expect(req.headers['Authorization'], 'Bearer $sessionToken');
          final body = jsonDecode(req.body) as Map<String, dynamic>;
          bodies.add(body);
          return http.Response(jsonEncode({'available': body['enabled']}), 200);
        }));
    final positions = StreamController<QaGpsFix>(sync: true);
    var consent = false;
    var assigned = true;
    final publisher = QaPilotGpsPublisher(send: api.publishGps,
        canStart: () => consent, isAssigned: (id) async => assigned && id == orderId,
        positions: () => positions.stream,
        clock: () => DateTime.fromMillisecondsSinceEpoch(100000));
    try {
      expect(await publisher.start(orderId), false);
      consent = true;
      assigned = false;
      expect(await publisher.start(orderId), false);
      expect(positions.hasListener, false);
      expect(bodies, isEmpty);
      assigned = true;
      expect(await publisher.start(orderId), true);
      positions.add(const QaGpsFix(1.25, 2.5, 100));
      await publisher.stop();
      positions.add(const QaGpsFix(2, 3, 102));
      expect(positions.hasListener, false);
      expect(bodies, [
        {'enabled': true, 'latitude': 1.25, 'longitude': 2.5, 'captured_at': 100},
        {'enabled': false, 'captured_at': 101},
      ]);
    } finally {
      await publisher.stop();
      await positions.close();
    }
  });
}
