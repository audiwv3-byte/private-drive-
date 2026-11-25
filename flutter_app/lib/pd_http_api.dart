import 'dart:convert';

import 'package:http/http.dart' as http;

/// Shared network transport for the Android app and browser-based test client.
/// Callers supply only public HTTPS API endpoints; credentials are never added
/// to URLs. Browser CORS policy is enforced by Safari/Chrome.
class PdHttpApi {
  const PdHttpApi();

  static Uri secureUri(String baseUrl, String path) {
    final base = Uri.tryParse(baseUrl);
    if (base == null || base.scheme != 'https' || base.host.isEmpty ||
        base.userInfo.isNotEmpty) {
      throw const FormatException('Безопасный адрес API не настроен.');
    }
    final uri = base.resolve(path);
    if (uri.scheme != 'https' || uri.host != base.host ||
        uri.port != base.port || uri.userInfo.isNotEmpty) {
      throw const FormatException('Недопустимый адрес API.');
    }
    return uri;
  }

  Future<Map<String, dynamic>> postJson(
    Uri uri,
    Map<String, String> payload, {
    http.Client? client,
    String? bearerToken,
    Duration timeout = const Duration(seconds: 10),
  }) async {
    if (uri.scheme != 'https' || uri.userInfo.isNotEmpty) {
      throw const FormatException('HTTPS обязателен.');
    }
    final owned = client == null;
    final transport = client ?? http.Client();
    try {
      final request = http.Request('POST', uri)
        ..followRedirects = false
        ..headers['Content-Type'] = 'application/json; charset=utf-8'
        ..body = jsonEncode(payload);
      if (bearerToken != null) {
        request.headers['Authorization'] = 'Bearer $bearerToken';
      }
      final response = await transport.send(request).timeout(timeout);
      final body = await http.Response.fromStream(response).timeout(timeout);
      return _decode(body);
    } finally {
      if (owned) transport.close();
    }
  }

  Future<Map<String, dynamic>> getJson(
    Uri uri, {
    http.Client? client,
    Duration timeout = const Duration(seconds: 7),
  }) async {
    if (uri.scheme != 'https' || uri.userInfo.isNotEmpty) {
      throw const FormatException('HTTPS обязателен.');
    }
    final owned = client == null;
    final transport = client ?? http.Client();
    try {
      final response = await transport.get(uri).timeout(timeout);
      return _decode(response);
    } finally {
      if (owned) transport.close();
    }
  }

  Map<String, dynamic> _decode(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      String? errorCode;
      try {
        final decoded = jsonDecode(utf8.decode(response.bodyBytes));
        if (decoded is Map<String, dynamic> && decoded['error'] is String) {
          errorCode = decoded['error'] as String;
        }
      } catch (_) { /* An HTML error page must still become an HTTP error. */ }
      throw PdHttpStatusException(response.statusCode, errorCode: errorCode);
    }
    final body = jsonDecode(utf8.decode(response.bodyBytes));
    if (body is! Map<String, dynamic>) {
      throw const FormatException('Некорректный ответ сервера.');
    }
    return body;
  }
}

class PdHttpStatusException implements Exception {
  const PdHttpStatusException(this.statusCode, {this.errorCode});

  final int statusCode;
  final String? errorCode;

  @override
  String toString() => 'Запрос отклонён (HTTP $statusCode).';
}
