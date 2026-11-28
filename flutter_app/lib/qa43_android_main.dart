import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import 'main.dart' as app;
import 'native_orders_api.dart';
import 'pd_http_api.dart';

Future<void> main() async {
  const origin = PdHttpApi.configuredOrigin;
  const ca = String.fromEnvironment('PD_QA43_LAB_CA');
  if (!Platform.isAndroid || !NativeOrdersApi.qaCheckout ||
      !const bool.fromEnvironment('PD_ISOLATED_DEVICE_QA') ||
      !PdHttpApi.isSecureOrigin(origin) || ca.isEmpty) {
    throw StateError('The QA43 Android lab origin and CA are required.');
  }
  final host = InternetAddress.tryParse(Uri.parse(origin).host);
  final bytes = host?.rawAddress;
  if (bytes == null || bytes.length != 4 || !(bytes[0] == 10 ||
      (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
      (bytes[0] == 192 && bytes[1] == 168))) {
    throw StateError('The QA43 Android origin must be on a private IPv4 network.');
  }
  final trust = SecurityContext(withTrustedRoots: true)
    ..setTrustedCertificatesBytes(base64Decode(ca));
  await http.runWithClient(app.main, () => IOClient(HttpClient(context: trust)));
}
