import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../lib/native_pilot_orders.dart';
import '../lib/pd_http_api.dart';
import '../lib/qa_pilot_gps.dart';

const order = '05cdbc84-0930-4c52-baa1-149a03190d78';
const token = 'qa28-synthetic-session-for-test-only-not-a-secret';

void main() {
  test('QA28 API matches QA27 and blocks redirects and foreign hosts', () async {
    expect(NativePilotOrdersApi.qaGpsEnabled, isTrue);
    final payloads = <Map<String, dynamic>>[];
    final api = NativePilotOrdersApi(baseUrl: NativePilotOrdersApi.stage,
      token: token, client: MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.path, '/native-pilot-orders/$order/gps');
        expect(req.headers['authorization'], 'Bearer $token');
        expect(req.followRedirects, isFalse);
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        payloads.add(body);
        return http.Response(jsonEncode({'available':body['enabled']}),200);
      }));
    await api.publishGps(order,const QaGpsFix(1.25,2.5,100),100);
    await api.publishGps(order,null,101);
    expect(payloads,[{'enabled':true,'captured_at':100,'latitude':1.25,'longitude':2.5},
      {'enabled':false,'captured_at':101}]);
    await expectLater(api.publishGps('invalid',null,102),throwsFormatException);
    await expectLater(api.publishGps(order,const QaGpsFix(91,2,102),102),throwsFormatException);
    final foreign = NativePilotOrdersApi(baseUrl:'https://elsewhere.invalid',
      token:token,client:MockClient((_) async {fail('No foreign network');}));
    await expectLater(foreign.publishGps(order,null,102),throwsFormatException);
    final redirected = NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.stage,
      token:token,client:MockClient((_) async => http.Response('',302)));
    await expectLater(redirected.publishGps(order,null,102),
      throwsA(isA<PdHttpStatusException>()));
  }, skip: !NativePilotOrdersApi.qaGpsEnabled);

  test('GPS is disabled without both QA flags', () async {
    final api = NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.stage,
      token:token,client:MockClient((_) async {fail('GPS must not send without QA flags');}));
    await expectLater(api.publishGps(order,null,100),throwsFormatException);
  }, skip: NativePilotOrdersApi.qaGpsEnabled);

  testWidgets('consented publisher keeps sending on simulated pause and stops when assignment ends',
    (tester) async {
    final positions = StreamController<QaGpsFix>(sync: true);
    final sent = <QaGpsFix?>[];
    var assigned = false;
    var now = 100;
    final publisher = QaPilotGpsPublisher(
      send:(id,fix,stamp) async {expect(id,order);sent.add(fix);},
      isAssigned:(id) async => assigned && id == order,
      positions:() => positions.stream,
      clock:() => DateTime.fromMillisecondsSinceEpoch(now*1000));
    expect(await publisher.start(order),isFalse);
    expect(sent,isEmpty);
    assigned = true;
    expect(await publisher.start(order),isTrue);
    positions.add(const QaGpsFix(1.25,2.5,100));
    await tester.pump(Duration.zero);
    expect(sent.whereType<QaGpsFix>().length,1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    now = 105;
    positions.add(const QaGpsFix(1.5,2.5,105));
    await tester.pump(Duration.zero);
    expect(sent.whereType<QaGpsFix>().length,2);
    positions.add(const QaGpsFix(1.0,2.5,100));
    await tester.pump(Duration.zero);
    expect(sent.whereType<QaGpsFix>().length,2);
    assigned = false;
    now = 115;
    await tester.pump(const Duration(seconds:11));
    await tester.pump(Duration.zero);
    expect(publisher.orderId,isNull);
    expect(sent.last,isNull);
    final count=sent.length;
    positions.add(const QaGpsFix(2,3,115));
    await tester.pump(Duration.zero);
    expect(sent.length,count);
    await publisher.stop();
    await positions.close();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  });

  test('stop serializes opt-out after the in-flight fix and drops subsequent fixes', () async {
    final positions=StreamController<QaGpsFix>();
    final pending=Completer<void>();
    final stamps=<int>[];
    final publisher=QaPilotGpsPublisher(
      isAssigned:(_) async=>true,
      positions:()=>positions.stream,
      clock:()=>DateTime.fromMillisecondsSinceEpoch(100000),
      send:(_,fix,stamp) async {stamps.add(stamp);if(fix!=null) await pending.future;});
    expect(await publisher.start(order),isTrue);
    positions.add(const QaGpsFix(1,2,100));
    await Future<void>.delayed(Duration.zero);
    final stopped=publisher.stop();
    positions.add(const QaGpsFix(1,2,101));
    expect(stamps,[100]);
    pending.complete();
    await stopped;
    expect(stamps,[100,101]);
    await positions.close();
  });
}
