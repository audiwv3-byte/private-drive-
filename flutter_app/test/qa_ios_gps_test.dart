import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/qa_pilot_gps.dart';
const order = '05cdbc84-0930-4c52-baa1-149a03190d78';
const token = 'qa-ios-synthetic-session-for-isolated-tests-only';
void main() {
  test('iOS QA transport refuses real host and non-injected client', () async {
    expect(NativePilotOrdersApi.qaIosGps, isTrue);
    final bad = NativePilotOrdersApi(baseUrl: NativePilotOrdersApi.stage, token: token,
      client: MockClient((_) async => throw StateError('unexpected network')));
    await expectLater(bad.publishGps(order,null,100),throwsFormatException);
    final noClient = NativePilotOrdersApi(baseUrl: NativePilotOrdersApi.qaIosBase, token: token);
    await expectLater(noClient.publishGps(order,null,100),throwsFormatException);
  });
  test('consent and assignment gate; synthetic HTTPS fix and opt out', () async {
    final sent = <Map<String,dynamic>>[];
    final api = NativePilotOrdersApi(baseUrl: NativePilotOrdersApi.qaIosBase,token:token,
      client:MockClient((req) async {
        expect(req.url.scheme,'https'); expect(req.url.host,'qa.invalid');
        expect(req.followRedirects,false);
        expect(req.headers['authorization'],'Bearer $token');
        expect(req.url.path,'/native-pilot-orders/$order/gps');
        final body=jsonDecode(req.body) as Map<String,dynamic>; sent.add(body);
        return http.Response(jsonEncode({'available':body['enabled']}),200);
      }));
    var consent=false; var assigned=false;
    final stream=StreamController<QaGpsFix>();
    final publisher=QaPilotGpsPublisher(send:api.publishGps,
      isAssigned: (id) async => assigned && id==order,
      canStart:()=>consent,positions:()=>stream.stream,
      clock:()=>DateTime.fromMillisecondsSinceEpoch(100000));
    expect(await publisher.start(order),false);
    assigned=true;
    expect(await publisher.start(order),false);
    consent=true;
    expect(await publisher.start(order),true);
    stream.add(const QaGpsFix(1,2,100));
    await Future<void>.delayed(Duration(milliseconds:20));
    await publisher.stop();
    expect(sent,[{'enabled':true,'captured_at':100,'latitude':1.0,'longitude':2.0},
      {'enabled':false,'captured_at':101}]);
    await stream.close();
  });
}
