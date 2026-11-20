import 'dart:convert';
import 'dart:io';

/// Native client for an explicitly configured isolated demo server only.
/// Credentials are supplied by the tester at runtime and never persisted.
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
  RemoteDemoClient(String address, String token)
      : _base = _safeBase(address),
        _token = _checkToken(token) {
    _http.connectionTimeout = const Duration(seconds: 6);
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
  final HttpClient _http = HttpClient();

  Future<Map<String, dynamic>> _request(String method, String path,
      [Map<String, dynamic>? payload]) async {
    if (!path.startsWith('/v1/') || path.contains('..')) {
      throw const RemoteDemoException('Недопустимый путь API');
    }
    try {
      final request = await _http.openUrl(method, _base.resolve(path))
          .timeout(const Duration(seconds: 8));
      request.followRedirects = false;
      request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $_token');
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (payload != null) {
        // Python's isolated HTTP server rejects chunked uploads and requires
        // a Content-Length. HttpClientRequest.write() can use chunked framing
        // when no length is specified, even though the JSON itself is valid.
        final bytes = utf8.encode(jsonEncode(payload));
        request.headers.contentType = ContentType.json;
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      final response = await request.close()
          .timeout(const Duration(seconds: 10));
      if (response.statusCode >= 300 && response.statusCode < 400) {
        throw const RemoteDemoException('Перенаправления сервера запрещены');
      }
      final body = await utf8.decoder.bind(response).join()
          .timeout(const Duration(seconds: 10));
      if (body.length > 128 * 1024) {
        throw const RemoteDemoException('Слишком большой ответ сервера');
      }
      final data = jsonDecode(body);
      if (data is! Map<String, dynamic>) {
        throw const RemoteDemoException('Недопустимый ответ тестового сервера');
      }
      if (response.statusCode >= 400) {
        throw RemoteDemoException(
          data['error'] is String ? data['error'] as String : 'Ошибка API',
          response.statusCode,
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
    _http.close(force: true);
  }
}
