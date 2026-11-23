import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'native_session.dart';

/// Keychain (iOS) / encrypted Android storage. No SharedPreferences tokens.
/// All validation happens again against the server after app restart.
class PdNativeSessionVault {
  const PdNativeSessionVault({this.storage = const FlutterSecureStorage()});

  final FlutterSecureStorage storage;
  static const _key = 'pd_native_session_v1';

  Future<void> save(PdNativeSession session) async {
    if (!session.active || session.token.length < 40 ||
        session.token.length > 256 || session.userId.isEmpty ||
        !const {'passenger', 'pilot', 'admin'}.contains(session.role)) {
      throw const FormatException('Invalid verified native session');
    }
    await storage.write(key: _key, value: jsonEncode({
      'token': session.token,
      'user_id': session.userId,
      'role': session.role,
      'expires_at': session.expiresAt.toUtc().millisecondsSinceEpoch,
    }));
  }

  Future<PdNativeSession?> read() async {
    final raw = await storage.read(key: _key);
    if (raw == null) return null;
    try {
      final data = jsonDecode(raw);
      if (data is! Map<String, dynamic>) return null;
      final token = data['token'], id = data['user_id'],
          role = data['role'], expires = data['expires_at'];
      if (token is! String || token.length < 40 || token.length > 256 ||
          id is! String || id.isEmpty || role is! String ||
          !const {'passenger', 'pilot', 'admin'}.contains(role) ||
          expires is! int) return null;
      final result = PdNativeSession(
        token: token, userId: id, role: role,
        expiresAt: DateTime.fromMillisecondsSinceEpoch(expires, isUtc: true));
      return result.active ? result : null;
    } catch (_) {
      // Corrupt or expired content is never promoted to an active login.
      // Do not delete a token on network failure or invalid metadata.
      return null;
    }
  }

  /// Call only after HTTP 200 confirms current-device server logout.
  Future<void> clearAfterConfirmedLogout() => storage.delete(key: _key);
}
