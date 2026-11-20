import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/pd_http_api.dart';

void main() {
  const api = PdHttpApi();

  test('HTTPS API path stays on configured origin', () {
    expect(
      PdHttpApi.secureUri('https://auth.example.test', '/native-auth/request-code')
          .toString(),
      'https://auth.example.test/native-auth/request-code',
    );
    expect(
      () => PdHttpApi.secureUri('http://auth.example.test', '/native-auth/request-code'),
      throwsFormatException,
    );
    expect(
      () => PdHttpApi.secureUri('https://auth.example.test', 'https://evil.test/'),
      throwsFormatException,
    );
    expect(
      () => PdHttpApi.secureUri('https://user:secret@auth.example.test', '/'),
      throwsFormatException,
    );
  });

  test('POST JSON request preserves OTP payload and parses response', () async {
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.toString(), 'https://auth.example.test/native-auth/request-code');
      expect(request.headers['content-type'], contains('application/json'));
      expect(jsonDecode(request.body), {
        'channel': 'phone',
        'destination': '+37060000000',
      });
      return http.Response('{"challenge_id":"opaque-test","expires_in":300}', 202,
          headers: {'content-type': 'application/json'});
    });
    final result = await api.postJson(
      Uri.parse('https://auth.example.test/native-auth/request-code'),
      {'channel': 'phone', 'destination': '+37060000000'},
      client: client,
    );
    expect(result['challenge_id'], 'opaque-test');
    client.close();
  });

  test('GET routing GeoJSON is decoded on shared transport', () async {
    final client = MockClient((request) async {
      expect(request.method, 'GET');
      return http.Response('{"routes":[{"geometry":{"coordinates":[[25.2,54.7],[25.3,54.8]]}}]}', 200);
    });
    final result = await api.getJson(
      Uri.parse('https://router.project-osrm.org/route/v1/driving/example'),
      client: client,
    );
    expect(result['routes'], isA<List<dynamic>>());
    client.close();
  });

  test('HTTP errors and invalid bodies fail closed', () async {
    final fail = MockClient((_) async => http.Response('{"error":"disabled"}', 503));
    await expectLater(
      api.postJson(Uri.parse('https://auth.example.test/native-auth/request-code'),
          {'channel': 'phone'}, client: fail),
      throwsA(isA<PdHttpStatusException>().having(
          (e) => e.statusCode, 'statusCode', 503)),
    );
    fail.close();

    final malformed = MockClient((_) async => http.Response('[]', 200));
    await expectLater(
      api.getJson(Uri.parse('https://auth.example.test/health'), client: malformed),
      throwsFormatException,
    );
    malformed.close();
  });
}
