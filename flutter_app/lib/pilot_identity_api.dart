import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'pd_http_api.dart';

class PdIdentityApi {
  PdIdentityApi({required this.baseUrl, required this.token, this.client,
    this.allowLoopback = false});
  final bool allowLoopback;
  final String baseUrl;
  final String token;
  final http.Client? client;

  Future<Map<String, dynamic>> request(String method, String endpoint,
      [Map<String, dynamic>? payload]) async {
    final base = Uri.parse(baseUrl);
    if (!PdHttpApi.allowedScheme(base, allowLoopback: allowLoopback) || base.host.isEmpty ||
        base.userInfo.isNotEmpty || base.hasQuery || base.hasFragment) {
      throw const FormatException('HTTPS identity API required');
    }
    final uri = base.resolve('/native-identity/$endpoint');
    final owned = client == null;
    final transport = client ?? http.Client();
    try {
      final req = http.Request(method, uri)
        ..followRedirects = false
        ..headers['Authorization'] = 'Bearer $token'
        ..headers['Content-Type'] = 'application/json';
      if (payload != null) req.body = jsonEncode(payload);
      final response = await http.Response.fromStream(
        await transport.send(req).timeout(const Duration(seconds: 25)),
      ).timeout(const Duration(seconds: 25));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw StateError('Identity API ${response.statusCode}');
      }
      final result = jsonDecode(response.body);
      if (result is! Map<String, dynamic>) {
        throw const FormatException('Invalid identity response');
      }
      return result;
    } finally {
      if (owned) transport.close();
    }
  }

  Future<Map<String, dynamic>> status() => request('GET', 'status');
  Future<Map<String, dynamic>> submit(Uint8List photo) => request('POST', 'submit', {
    'photo': base64Encode(photo),
  });
}

class PdIdentityScope extends InheritedWidget {
  const PdIdentityScope({super.key, required this.api, required super.child});
  final PdIdentityApi api;
  static PdIdentityApi? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<PdIdentityScope>()?.api;
  @override
  bool updateShouldNotify(PdIdentityScope oldWidget) => oldWidget.api != api;
}
