import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/qa_pilot_gps.dart';
import '../lib/pd_http_api.dart';

const orderId='05cdbc84-0930-4c52-baa1-149a03190d78';
const testToken='qa-release-synthetic-pilot-token-not-for-real-auth';

void main() {
  test('release GPS sends authenticated HTTPS without any internal QA flags', () async {
    expect(const bool.fromEnvironment('PD_INTERNAL_QA'), isFalse);
    expect(const bool.fromEnvironment('PD_QA28_GPS'), isFalse);
    expect(NativePilotOrdersApi.qa29Loopback,isFalse);
    final packets=<Map<String,dynamic>>[];
    final api=NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.stage,
      token:testToken,client:MockClient((req) async {
        expect(req.url.scheme,'https');
        expect(req.url.host,Uri.parse(NativePilotOrdersApi.stage).host);
        expect(req.url.path,'/native-pilot-orders/$orderId/gps');
        expect(req.headers['authorization'],'Bearer $testToken');
        expect(req.followRedirects,isFalse);
        final body=jsonDecode(req.body) as Map<String,dynamic>;
        packets.add(body);
        return http.Response(jsonEncode({'available':body['enabled']}),200);
      }));
    await api.publishGps(orderId,const QaGpsFix(54.6872,25.2797,200),200);
    await api.publishGps(orderId,null,201);
    expect(packets.map((e)=>e['enabled']).toList(),[true,false]);
    final foreign=NativePilotOrdersApi(baseUrl:'https://attacker.invalid',token:testToken,
      client:MockClient((_) async {fail('Bearer must not leave approved origin');}));
    await expectLater(foreign.publishGps(orderId,null,202),throwsFormatException);
    final loopback=NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.qa29Base,
      token:testToken,client:MockClient((_) async {fail('Release must reject cleartext');}));
    await expectLater(loopback.publishGps(orderId,null,203),throwsFormatException);
    final redirect=NativePilotOrdersApi(baseUrl:NativePilotOrdersApi.stage,
      token:testToken,client:MockClient((_) async=>http.Response('',302)));
    await expectLater(redirect.publishGps(orderId,null,204),
      throwsA(isA<PdHttpStatusException>()));
  });

  test('consent and assignment gate, background stream, revocation and stop', () async {
    final binding=TestWidgetsFlutterBinding.ensureInitialized();
    binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final positions=StreamController<QaGpsFix>(sync:true);
    final sent=<QaGpsFix?>[];
    var assigned=false,consent=false;
    var now=300;
    final stopped=Completer<void>();
    final publisher=QaPilotGpsPublisher(
      send:(_,fix,stamp) async {sent.add(fix);},
      isAssigned:(id) async=>assigned&&id==orderId,
      canStart:()=>consent,
      positions:()=>positions.stream,
      checkInterval:const Duration(milliseconds:20),
      clock:()=>DateTime.fromMillisecondsSinceEpoch(now*1000),
      onStopped:(){if(!stopped.isCompleted) stopped.complete();});
    try {
      expect(await publisher.start(orderId),isFalse);
      expect(sent,isEmpty);
      assigned=true;
      expect(await publisher.start(orderId),isFalse);
      consent=true;
      expect(await publisher.start(orderId),isTrue);
      positions.add(const QaGpsFix(54.6,25.2,300));
      await Future<void>.delayed(Duration.zero);
      binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      now=303;
      positions.add(const QaGpsFix(54.7,25.3,303));
      await Future<void>.delayed(Duration.zero);
      expect(sent.whereType<QaGpsFix>().length,2);
      assigned=false;
      now=310;
      await stopped.future.timeout(const Duration(seconds:3));
      expect(sent.last,isNull);
      positions.add(const QaGpsFix(54.8,25.4,311));
      await Future<void>.delayed(Duration.zero);
      expect(sent.whereType<QaGpsFix>().length,2);
    } finally {
      await publisher.stop();
      await positions.close();
      binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    }
  });
}
