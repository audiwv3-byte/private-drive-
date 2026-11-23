import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_session_vault.dart';
import 'package:private_drive/native_session_manager.dart';

const token = 'synthetic-encrypted-token-abcdefghijklmnopqrstuvwxyz1234567890';
const api = 'https://native-auth.example.test';

void main() {
  late PdNativeSessionVault vault;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
    vault = const PdNativeSessionVault();
  });

  PdNativeSession valid({String role = 'pilot', String userId = 'pilot-123',
      Duration lifetime = const Duration(hours: 3)}) =>
      PdNativeSession(token: token, role: role, userId: userId,
        expiresAt: DateTime.now().add(lifetime));

  test('encrypted token survives a new vault instance but role comes from server', () async {
    await vault.save(valid(role: 'pilot'));
    final serverExpiry = DateTime.now().add(const Duration(hours: 1))
        .millisecondsSinceEpoch ~/ 1000;
    final client = MockClient((request) async {
      expect(request.method, 'GET');
      expect(request.url.toString(), '$api/native-auth/session');
      expect(request.url.query, isEmpty);
      expect(request.body, isEmpty);
      expect(request.headers['authorization'], 'Bearer $token');
      return http.Response(jsonEncode({
        'user_id':'pilot-123', 'role':'passenger',
        'expires_at':serverExpiry,
      }), 200);
    });
    final manager = PdNativeSessionManager(baseUrl: api,
      vault: const PdNativeSessionVault(), client: client);
    final restored = await manager.restore();
    expect(restored?.userId, 'pilot-123');
    expect(restored?.role, 'passenger');
    expect(restored?.canPilot, isFalse);
    expect(restored?.expiresAt.isBefore(DateTime.now().add(const Duration(hours: 2))),
        isTrue);
    client.close();
  });

  test('revoked token is never restored and is not deleted on 401', () async {
    await vault.save(valid());
    final client = MockClient((_) async =>
      http.Response('{"error":"invalid_session"}', 401));
    final manager = PdNativeSessionManager(baseUrl: api, vault:vault,client:client);
    expect(await manager.restore(), isNull);
    expect((await vault.read())?.token, token);
    client.close();
  });

  test('network outage keeps encrypted token without granting access', () async {
    await vault.save(valid());
    final client = MockClient((_) async => throw Exception('offline'));
    final manager = PdNativeSessionManager(baseUrl:api,vault:vault,client:client);
    expect(await manager.restore(), isNull);
    expect((await vault.read())?.role, 'pilot');
    client.close();
  });

  test('mismatched server identity and expired server session are rejected', () async {
    await vault.save(valid());
    for (final data in [
      {'user_id':'other','role':'admin','expires_at':9999999999},
      {'user_id':'pilot-123','role':'admin','expires_at':1},
      {'user_id':'pilot-123','role':'pilot_dispatcher','expires_at':9999999999},
    ]) {
      final client=MockClient((_) async => http.Response(jsonEncode(data),200));
      final manager=PdNativeSessionManager(baseUrl:api,vault:vault,client:client);
      expect(await manager.restore(),isNull);
      client.close();
    }
    expect((await vault.read())?.token, token);
  });

  test('an expired encrypted token cannot restore or grant privileges', () async {
    await vault.save(valid(lifetime:const Duration(milliseconds: 1)));
    await Future<void>.delayed(const Duration(milliseconds: 5));
    expect(await vault.read(), isNull);
  });

  test('only confirmed logout removes matching encrypted token', () async {
    await vault.save(valid());
    final manager=PdNativeSessionManager(baseUrl:api,vault:vault);
    await manager.forgetConfirmedSession('wrong-token');
    expect((await vault.read())?.token,token);
    await manager.forgetConfirmedSession(token);
    expect(await vault.read(),isNull);
  });

  test('reinstall cannot reuse old Keychain record without install marker', () async {
    await vault.save(valid());
    expect((await vault.read())?.token, token);
    // Simulate app-data deletion on reinstall while Keychain still retains item.
    SharedPreferences.setMockInitialValues({});
    final fresh = const PdNativeSessionVault();
    expect(await fresh.read(), isNull);
    // A new verified OTP login establishes a new installation marker.
    await fresh.save(valid(userId: 'new-verified-account'));
    expect((await fresh.read())?.userId, 'new-verified-account');
  });

  test('restored preferences with a mismatching install id reject old token', () async {
    await vault.save(valid());
    SharedPreferences.setMockInitialValues({
      'pd_native_install_id_v1': 'restored-different-installation',
    });
    expect(await const PdNativeSessionVault().read(), isNull);
  });

  test('plaintext local preferences are never used for credentials', () async {
    await vault.save(valid());
    final prefs = await SharedPreferences.getInstance();
    final values = prefs.getKeys().map((key) => prefs.get(key).toString()).join();
    expect(values, isNot(contains(token)));
    expect(prefs.getString('pd_native_install_id_v1'), isNotEmpty);
    expect((await vault.read())?.token, token);
  });
}
