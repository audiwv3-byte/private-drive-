import 'dart:convert';

import 'package:http/http.dart' as http;

import 'pd_http_api.dart';

/// Native Android/iOS logout transport. Does not persist credentials or
/// include the bearer token in the URL, query or request body.
class PdNativeLogoutApi {
  const PdNativeLogoutApi({required this.baseUrl, this.client});

  final String baseUrl;
  final http.Client? client;

  Future<void> revokeCurrentDevice(String accessToken) async {
    if (accessToken.length < 40 ||
        accessToken.length > 256 ||
        RegExp(r'\s').hasMatch(accessToken)) {
      throw const FormatException('Недействительная сессия.');
    }
    final uri = PdHttpApi.secureUri(baseUrl, '/native-auth/logout');
    final transport = client ?? http.Client();
    try {
      final request = http.Request('POST', uri)
        ..headers['Authorization'] = 'Bearer $accessToken'
        ..headers['Accept'] = 'application/json';
      // An explicitly empty body: token must NEVER appear here.
      final response = await transport.send(request)
          .timeout(const Duration(seconds: 10));
      final body = await http.Response.fromStream(response)
          .timeout(const Duration(seconds: 10));
      if (body.statusCode != 200 ||
          jsonDecode(body.body)['status'] != 'logged_out') {
        throw PdHttpStatusException(body.statusCode);
      }
    } finally {
      if (client == null) transport.close();
    }
  }
}
