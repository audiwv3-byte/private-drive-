import 'dart:convert';

import 'package:http/http.dart' as http;

/// Native and browser client for an explicitly configured isolated demo server.
/// Test credentials are supplied at runtime and never persisted.
abstract class RemoteTripGateway {
  Future<Map<String, dynamic>> get(String path);
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> data);
  void close() {}
}

class RemoteDemoException implements Exception {
  const RemoteDemoException(this.message, [this.status]);
  final String message;
  final int? status;

  @override
  String toString() => message;
}

class RemoteDemoClient implements RemoteTripGateway {
  RemoteDemoClient(String address, String token, {
    String? cabin, http.Client? httpClient,
  }) : _base = _safeBase(address),
       _token = _checkToken(token),
       _cabin = cabin,
       _http = httpClient ?? http.Client() {
    if (cabin != null &&
        !const {'passenger', 'pilot', 'dispatcher'}.contains(cabin)) {
      throw const RemoteDemoException('Недопустимый кабинет');
    }
  }

  static Uri _safeBase(String address) {
    final uri = Uri.tryParse(address.trim());
    if (uri == null ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        !(uri.scheme == 'https' ||
            (uri.scheme == 'http' &&
             (uri.host == '127.0.0.1' || uri.host == 'localhost')))) {
      throw const RemoteDemoException(
        'Укажи HTTPS-адрес отдельного тестового сервера',
      );
    }
    return uri;
  }

  static String _checkToken(String token) {
    if (token.length < 32 || token.trim() != token) {
      throw const RemoteDemoException(
        'Тестовый токен должен содержать не менее 32 символов',
      );
    }
    return token;
  }

  final Uri _base;
  final String _token;
  final String? _cabin;
  final http.Client _http;

  Future<Map<String, dynamic>> _request(String method, String path,
      [Map<String, dynamic>? payload]) async {
    if (!path.startsWith('/v1/') || path.contains('..')) {
      throw const RemoteDemoException('Недопустимый путь API');
    }
    try {
      final request = http.Request(method, _base.resolve(path))
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $_token'
        ..headers['Accept'] = 'application/json';
      if (_cabin != null) request.headers['X-PD-Cabin'] = _cabin!;
      if (payload != null) {
        request.headers['Content-Type'] = 'application/json; charset=utf-8';
        request.bodyBytes = utf8.encode(jsonEncode(payload));
      }
      final streamed = await _http.send(request)
          .timeout(const Duration(seconds: 10));
      if (streamed.statusCode >= 300 && streamed.statusCode < 400) {
        throw const RemoteDemoException('Перенаправления сервера запрещены');
      }
      // Buffer at most 128 KiB, independent of any advertised Content-Length.
      final bytes = <int>[];
      await for (final chunk in streamed.stream.timeout(
          const Duration(seconds: 10))) {
        bytes.addAll(chunk);
        if (bytes.length > 128 * 1024) {
          throw const RemoteDemoException('Слишком большой ответ сервера');
        }
      }
      final data = jsonDecode(utf8.decode(bytes));
      if (data is! Map<String, dynamic>) {
        throw const RemoteDemoException('Недопустимый ответ тестового сервера');
      }
      if (streamed.statusCode >= 400) {
        throw RemoteDemoException(
          data['error'] is String ? data['error'] as String : 'Ошибка API',
          streamed.statusCode,
        );
      }
      return data;
    } on RemoteDemoException {
      rethrow;
    } on Exception {
      throw const RemoteDemoException(
        'Нет безопасного соединения с тестовым сервером',
      );
    }
  }

  @override
  Future<Map<String, dynamic>> get(String path) => _request('GET', path);

  @override
  Future<Map<String, dynamic>> post(
          String path, Map<String, dynamic> data) =>
      _request('POST', path, data);

  @override
  void close() {
    _http.close();
  }
}
