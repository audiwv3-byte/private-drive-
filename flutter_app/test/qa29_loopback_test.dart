import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/qa_pilot_gps.dart';

void main() {
  test('loads the synthetic assignment only over the approved QA29 transport', () async {
    const token = 'qa29-synthetic-pilot-session-not-a-real-credential';
    const id = '05cdbc84-0930-4c52-baa1-149a03190d78';
    var requests = 0;
    final client = MockClient((req) async {
      requests++;
      expect(req.method, 'GET');
      expect(req.url.toString(), '${NativePilotOrdersApi.qa29Base}/native-pilot-orders');
      expect(req.followRedirects, isFalse);
      expect(req.headers['authorization'], 'Bearer $token');
      return http.Response(jsonEncode({
        'payment_mode': 'disabled',
        'orders': [{
          'order_id': id, 'from': 'Synthetic A', 'to': 'Synthetic B',
          'trip_date': '2027-01-01', 'trip_time': '12:00', 'status': 'assigned',
        }],
      }), 200);
    });
    NativePilotOrdersApi api(String base, String session) =>
        NativePilotOrdersApi(baseUrl: base, token: session, client: client);
    final orders = await api(NativePilotOrdersApi.qa29Base, token).load();
    expect(orders.single.orderId, id);
    for (final base in [NativePilotOrdersApi.stage, 'http://127.0.0.1:18730']) {
      await expectLater(api(base, token).load(), throwsFormatException);
    }
    await expectLater(api(NativePilotOrdersApi.qa29Base, 'unapproved-session').load(),
        throwsFormatException);
    expect(requests, 1);
  }, skip: !NativePilotOrdersApi.qa29Loopback);

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
