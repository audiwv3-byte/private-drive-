import 'package:http/http.dart' as http;

import 'native_session.dart';
import 'pd_http_api.dart';

/// The closed beta may send invite codes only to the known isolated HTTPS API.
class PdClosedInviteApi {
  const PdClosedInviteApi({required this.baseUrl, this.client});

  static const stagingBaseUrl = 'https://private-drive-drbd.onrender.com';
  static final _codePattern = RegExp(r'^[A-Za-z0-9_-]{43}$');
  static final _sessionPattern = RegExp(r'^[A-Za-z0-9_-]{64}$');

  final String baseUrl;
  final http.Client? client;

  bool get enabled => baseUrl == stagingBaseUrl;

  static bool validCode(String code) =>
      code.length == 43 && _codePattern.hasMatch(code);

  Future<PdNativeSession> redeem(String code) async {
    if (!enabled || !validCode(code)) {
      throw const FormatException('Недопустимое приглашение.');
    }
    final uri = PdHttpApi.secureUri(baseUrl, '/native-auth/redeem-invite');
    final result = await const PdHttpApi().postJson(
      uri, {'invite_code': code}, client: client, followRedirects: false,
    );
    final token = result['access_token'];
    final userId = result['user_id'];
    final expiresAt = result['expires_at'];
    final now = DateTime.now();
    final epochSeconds = now.millisecondsSinceEpoch ~/ 1000;
    if (result['role'] != 'passenger' || result['token_type'] != 'Bearer' ||
        token is! String || token.length != 64 || !_sessionPattern.hasMatch(token) ||
        userId is! String || userId.isEmpty || userId.length > 128 ||
        expiresAt is! int || expiresAt <= epochSeconds ||
        expiresAt > epochSeconds + 8 * Duration.secondsPerDay) {
      throw const FormatException('Сервер не выдал корректную сессию.');
    }
    return PdNativeSession(
      token: token, userId: userId, role: 'passenger',
      expiresAt: DateTime.fromMillisecondsSinceEpoch(expiresAt * 1000),
    );
  }
}
