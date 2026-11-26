import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/qa_pilot_gps.dart';

void main() {
  test('QA29 accepts only local synthetic backend and never redirects', () async {
    const order = '05cdbc84-0930-4c52-baa1-149a03190d78';
    const token = 'qa29-synthetic-pilot-session-not-a-real-credential';
    var sends = 0;
    final client = MockClient((req) async {
      sends++;
      expect(req.url.toString(), '${NativePilotOrdersApi.qa29Base}/native-pilot-orders/$order/gps');
      expect(req.headers['authorization'],'Bearer $token');
      expect(req.followRedirects,isFalse);
      expect(jsonDecode(req.body),{'enabled':true,'captured_at':100,'latitude':1.25,'longitude':2.5});
      return http.Response('{"available":true}',200);
    });
    final api = NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.qa29Base,token:token,client:client);
    await api.publishGps(order,const QaGpsFix(1.25,2.5,100),100);
    for(final base in [NativePilotOrdersApi.stage,'http://127.0.0.1:18730','http://example.invalid:18729']){
      final wrong = NativePilotOrdersApi(baseUrl:base,token:token,client:client);
      await expectLater(wrong.publishGps(order,null,101),throwsFormatException);
    }
    final realToken = NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.qa29Base,token:'not-a-synthetic-token-xxxxxxxxxxxxxxxxxxxxxxxx',client:client);
    await expectLater(realToken.publishGps(order,null,101),throwsFormatException);
    expect(sends,1);
  },skip:!NativePilotOrdersApi.qa29Loopback);
}
