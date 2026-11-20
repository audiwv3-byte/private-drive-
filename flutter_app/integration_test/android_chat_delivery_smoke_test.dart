import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:private_drive/remote_sync_client.dart';

/// Android networking end-to-end test. The GitHub runner hosts the genuine,
/// isolated Python HTTP backend; adb reverse maps emulator loopback to it.
///
/// Two separately authenticated native clients run on ONE Android emulator.
/// This is NOT a claim that two physical phones were tested.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Android native passenger and pilot chat through isolated HTTP server',
      (tester) async {
    await tester.runAsync(() async {
      final passenger = RemoteDemoClient(
          'http://127.0.0.1:8765', 'p' * 40);
      final pilot = RemoteDemoClient(
          'http://127.0.0.1:8765', 'd' * 40);
      final outsider = RemoteDemoClient(
          'http://127.0.0.1:8765', 'q' * 40);
      try {
        final owner = await passenger.get('/v1/me');
        final driver = await pilot.get('/v1/me');
        expect(owner['role'], 'passenger');
        expect(owner['actor'], 'passenger_test');
        expect(driver['role'], 'pilot');
        expect(driver['actor'], 'pilot_test');

        final passengerCurrent = await passenger.get('/v1/current');
        final pilotCurrent = await pilot.get('/v1/current');
        final trip = passengerCurrent['trip'] as Map<String, dynamic>;
        final tripId = trip['id'] as String;
        expect(tripId.length, 32);
        expect((pilotCurrent['trip'] as Map<String, dynamic>)['id'], tripId);
        expect((await outsider.get('/v1/current'))['trip'], isNull);

        final endpoint = '/v1/trips/$tripId/messages';
        const clientIdPassenger = '11111111111111111111111111111111';
        final first = await passenger.post(endpoint, {
          'client_id': clientIdPassenger,
          'text': 'Пассажир: ожидаю у входа',
        });
        final firstMessage = first['message'] as Map<String, dynamic>;
        final firstSeq = firstMessage['seq'] as int;
        expect(firstMessage['role'], 'passenger');

        // A different independently authenticated client receives it.
        final pilotPoll = await pilot.get('$endpoint?after=0');
        final pilotRows = pilotPoll['messages'] as List<dynamic>;
        expect(pilotRows.length, 1);
        expect((pilotRows.single as Map<String, dynamic>)['body'],
            'Пассажир: ожидаю у входа');

        // A retried POST has exactly-once persistence.
        final retry = await passenger.post(endpoint, {
          'client_id': clientIdPassenger,
          'text': 'This duplicate must not overwrite the first message',
        });
        expect((retry['message'] as Map<String, dynamic>)['seq'], firstSeq);

        final response = await pilot.post(endpoint, {
          'client_id': '22222222222222222222222222222222',
          'text': 'Пилот: подъезжаю',
        });
        final pilotSeq = (response['message'] as Map<String, dynamic>)['seq'];
        expect(pilotSeq, greaterThan(firstSeq));

        final passengerPoll =
            await passenger.get('$endpoint?after=$firstSeq');
        final passengerRows = passengerPoll['messages'] as List<dynamic>;
        expect(passengerRows.length, 1);
        expect((passengerRows.single as Map<String, dynamic>)['body'],
            'Пилот: подъезжаю');
        expect((await passenger.get('$endpoint?after=$pilotSeq'))['messages'],
            isEmpty);

        // Another passenger identity cannot read another user's trip.
        try {
          await outsider.get(endpoint);
          fail('Outsider must not access passenger/pilot chat');
        } on RemoteDemoException catch (e) {
          expect(e.status, 404);
        }
        expect((await pilot.get(endpoint))['messages'], hasLength(2));
      } finally {
        passenger.close();
        pilot.close();
        outsider.close();
      }
    });
  });
}
