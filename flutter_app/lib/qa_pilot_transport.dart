// Transport for historical isolated QA entry points and their fixtures.
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'native_pilot_orders.dart';
import 'pd_http_api.dart';

class QaPilotOrdersApi extends NativePilotOrdersApi {
  const QaPilotOrdersApi({required super.baseUrl, required super.token, http.Client? client})
      : _injected = client != null, super(client: client);

  final bool _injected;
  static const stage = 'https://legacy-qa.invalid';


  static const qaGpsEnabled = bool.fromEnvironment('PD_QA28_GPS') &&
      bool.fromEnvironment('PD_INTERNAL_QA');

  // QA29 is a separate debug-only APK. It can never send a real session
  // to plaintext HTTP, or reach the existing staging/production service.
  static const qaIosGps = bool.fromEnvironment('PD_QA_IOS_GPS') && qaGpsEnabled;
  static const qaIosBase = 'https://qa.invalid';
  bool get _qaIosAllowed => qaIosGps && baseUrl == qaIosBase &&
      token.startsWith('qa-ios-synthetic-') && token.length >= 40 &&
      _injected;
  static const qa29Loopback = bool.fromEnvironment('PD_QA29_LOOPBACK') &&
      qaGpsEnabled && kDebugMode;
  static const qa29Base = 'http://127.0.0.1:18729';
  bool get _qa29Allowed => qa29Loopback && baseUrl == qa29Base &&
      token.startsWith('qa29-synthetic-') && token.length >= 40;
  @override
  bool get originAllowed => qaIosGps ? _qaIosAllowed : (qa29Loopback ? _qa29Allowed :
      baseUrl == stage);
  @override
  bool get gpsEnabled => qaGpsEnabled && originAllowed;

  @override
  Uri endpoint(String path) {
    if (!originAllowed) throw const FormatException('Unapproved pilot API');
    if (_qa29Allowed) return Uri.parse(qa29Base).resolve(path);
    return PdHttpApi.secureUri(baseUrl, path);
  }
}
