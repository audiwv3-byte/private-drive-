import 'dart:convert';

import 'package:http/http.dart' as http;
import 'native_session.dart';
import 'native_session_vault.dart';
import 'pd_http_api.dart';

/// The persisted role is untrusted. Restore ONLY after checking current
/// server-side role and revocation through HTTPS.
class PdNativeSessionManager {
  const PdNativeSessionManager({
    required this.baseUrl,
    required this.vault,
    this.client,
  });

  final String baseUrl;
  final PdNativeSessionVault vault;
  final http.Client? client;

  Future<void> remember(PdNativeSession session) => vault.save(session);

  Future<PdNativeSession?> restore() async {
    final stored = await vault.read();
    if (stored == null) return null;
    final uri = PdHttpApi.secureUri(baseUrl, '/native-auth/session');
    final owned = client == null;
    final transport = client ?? http.Client();
    try {
      final request = http.Request('GET', uri)
        ..headers['Authorization'] = 'Bearer ${stored.token}'
        ..headers['Accept'] = 'application/json';
      final streamed = await transport.send(request)
          .timeout(const Duration(seconds: 8));
      final response = await http.Response.fromStream(streamed)
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return null;
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) return null;
      final id = decoded['user_id'];
      final role = decoded['role'];
      final expiry = decoded['expires_at'];
      if (id != stored.userId || role is! String ||
          !const {'passenger', 'pilot', 'admin'}.contains(role) ||
          expiry is! int) return null;
      final serverExpiry = DateTime.fromMillisecondsSinceEpoch(
        expiry * 1000, isUtc: true);
      final finalExpiry = serverExpiry.isBefore(stored.expiresAt)
          ? serverExpiry : stored.expiresAt;
      if (!DateTime.now().isBefore(finalExpiry)) return null;
      return PdNativeSession(token: stored.token, userId: id as String,
        role: role, expiresAt: finalExpiry);
    } catch (_) {
      // Connectivity failures do not delete the encrypted token and never
      // grant offline staff privileges.
      return null;
    } finally {
      if (owned) transport.close();
    }
  }

  /// Called only after a confirmed HTTP logout for this exact session.
  Future<void> forgetConfirmedSession(String token) async {
    final current = await vault.read();
    if (current?.token == token) {
      await vault.clearAfterConfirmedLogout();
    }
  }
}
