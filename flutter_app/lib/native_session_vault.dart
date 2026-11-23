import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:math';
import 'native_session.dart';

/// Keychain (iOS) / encrypted Android storage. No SharedPreferences tokens.
/// All validation happens again against the server after app restart.
class PdNativeSessionVault {
  const PdNativeSessionVault({this.storage = const FlutterSecureStorage()});

  final FlutterSecureStorage storage;
  static const _key = 'pd_native_session_v1';
  static const _installKey = 'pd_native_install_id_v1';
  // iOS Keychain may survive app deletion. A non-secret installation marker
  // prevents a previous credential from being reused after reinstall.
  static const _ios = IOSOptions(
    accessibility: KeychainAccessibility.unlocked_this_device,
    synchronizable: false,
  );
  static const _android = AndroidOptions(
    storageNamespace: 'pd_native_auth_session',
  );

  Future<String?> _installationMarker({bool create = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final existing = prefs.getString(_installKey);
    if (existing != null && existing.isNotEmpty) return existing;
    if (!create) return null;
    final random = Random.secure();
    final marker = List<int>.generate(24, (_) => random.nextInt(256))
        .map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
    if (!await prefs.setString(_installKey, marker)) {
      throw StateError('Unable to initialize native install marker');
    }
    return marker;
  }

  Future<void> save(PdNativeSession session) async {
    if (!session.active || session.token.length < 40 ||
        session.token.length > 256 || session.userId.isEmpty ||
        !const {'passenger', 'pilot', 'admin'}.contains(session.role)) {
      throw const FormatException('Invalid verified native session');
    }
    final marker = await _installationMarker(create: true);
    await storage.write(key: _key, iOptions: _ios, aOptions: _android,
      value: jsonEncode({
      'installation': marker,
      'token': session.token,
      'user_id': session.userId,
      'role': session.role,
      'expires_at': session.expiresAt.toUtc().millisecondsSinceEpoch,
    }));
  }

  Future<PdNativeSession?> read() async {
    final marker = await _installationMarker();
    if (marker == null) return null;
    final raw = await storage.read(key: _key, iOptions: _ios, aOptions: _android);
    if (raw == null) return null;
    try {
      final data = jsonDecode(raw);
      if (data is! Map<String, dynamic> ||
          data['installation'] != marker) return null;
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
  Future<void> clearAfterConfirmedLogout() =>
      storage.delete(key: _key, iOptions: _ios, aOptions: _android);
}
