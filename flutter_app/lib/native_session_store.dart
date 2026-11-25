import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'native_session.dart';
import 'pd_http_api.dart';

class PdNativeSessionStore {
  PdNativeSessionStore(
    String baseUrl, {
    FlutterSecureStorage storage = const FlutterSecureStorage(),
    http.Client? client,
  }) : _baseUrl = baseUrl, _storage = storage, _client = client;

  final String _baseUrl;
  final FlutterSecureStorage _storage;
  final http.Client? _client;

  String get _key =>
      'pd_native_session_v1:${PdHttpApi.secureUri(_baseUrl, '/').origin}';

  Future<void> save(PdNativeSession session, String cabin) => _storage.write(
    key: _key,
    value: jsonEncode({'token': session.token, 'cabin': cabin}),
  );

  Future<(PdNativeSession, String)?> restore() async {
    final value = await _storage.read(key: _key);
    if (value == null) return null;
    final Object? data;
    try {
      data = jsonDecode(value);
    } on FormatException {
      await clear();
      return null;
    }
    final token = data is Map ? data['token'] : null;
    if (token is! String || !RegExp(r'^[A-Za-z0-9_-]{40,256}$').hasMatch(token)) {
      await clear();
      return null;
    }
    try {
      final response = await _post('/native-auth/session', token);
      final session = PdNativeSession.fromApi(response, savedToken: token);
      final cabin = switch (data is Map ? data['cabin'] : null) {
        'pilot' when session.canPilot => 'pilot',
        'dispatcher' when session.canDispatch => 'dispatcher',
        _ => 'passenger',
      };
      return (session, cabin);
    } on PdHttpStatusException catch (error) {
      if (error.statusCode != 401) rethrow;
      await clear();
      return null;
    }
  }

  Future<void> clear() => _storage.delete(key: _key);

  Future<void> revoke(PdNativeSession session) async {
    await _post('/native-auth/sign-out', session.token);
  }

  Future<Map<String, dynamic>> _post(String path, String token) =>
      const PdHttpApi().postJson(
        PdHttpApi.secureUri(_baseUrl, path),
        const {},
        client: _client,
        bearerToken: token,
      );
}
