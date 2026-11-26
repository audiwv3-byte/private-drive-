import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:geolocator/geolocator.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_orders_api.dart';
import 'package:private_drive/native_pilot_orders.dart';
import 'package:private_drive/pd_http_api.dart';
import 'package:private_drive/qa_pilot_gps.dart';

const origin = 'https://qa.invalid';
const id = '05cdbc84-0930-4c52-baa1-149a03190d78';
final token = List.filled(48, 'a').join();

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('QA42 native runtime: session, order contracts, consent and sensor opt-out', (tester) async {
    await tester.runAsync(() async {
      expect(PdHttpApi.configuredOrigin, origin);
      expect(const bool.fromEnvironment('PD_INTERNAL_QA'), false);
      final session = PdNativeSession.fromApi({'verified':true,'access_token':token,
        'user_id':'synthetic','token_type':'Bearer','role':'passenger','expires_in':60});
      expect(session.active, true);
      expect(session.canPilot, false);
      final gps = <Map<String,dynamic>>[];
      final client = MockClient((req) async {
        expect(req.url.host, 'qa.invalid');
        expect(req.followRedirects, false);
        expect(req.headers['Authorization'], 'Bearer $token');
        if (req.url.path.endsWith('/gps')) {
          final body = jsonDecode(req.body) as Map<String,dynamic>;
          gps.add(body);
          return http.Response(jsonEncode({'available':body['enabled']}),200);
        }
        if (req.url.path == '/native-orders') {
          return http.Response(jsonEncode({'payment_mode':'disabled','order_id':id,'status':'requested','orders':[]}),200);
        }
        return http.Response(jsonEncode({'payment_mode':'disabled','orders':[{
          'order_id':id,'from':'A','to':'B','trip_date':'2030-01-01','trip_time':'12:00','status':'assigned'}]}),200);
      });
      final passenger = NativeOrdersApi(origin,token,client:client);
      final pilot = NativePilotOrdersApi(baseUrl:origin,token:token,client:client);
      final order = await passenger({'request_id':NativeOrdersApi.requestId(),'from':'A','to':'B'});
      expect(order['order_id'],id);
      expect((await pilot.load()).single.orderId,id);
      var consent = false;
      final publisher = QaPilotGpsPublisher(send:pilot.publishGps,
        canStart:()=>consent,isAssigned:(order) async => order == id,
        positions:()=> Geolocator.getPositionStream(locationSettings: const LocationSettings(
          accuracy:LocationAccuracy.high,distanceFilter:0)).map((p)=>QaGpsFix(
          p.latitude,p.longitude,p.timestamp.millisecondsSinceEpoch ~/ 1000)));
      try {
        expect(await publisher.start(id),false);
        expect(gps,isEmpty);
        expect(await qaGpsPermission(),true);
        consent = true;
        expect(await publisher.start(id),true);
        final deadline = DateTime.now().add(const Duration(seconds:60));
        while(gps.isEmpty && DateTime.now().isBefore(deadline)) {
          await Future<void>.delayed(const Duration(seconds:1));
        }
        expect(gps,isNotEmpty,reason:'OS location stream must produce a fix');
        expect(gps.first['enabled'],true);
        await publisher.stop();
        expect(gps.last['enabled'],false);
        final count = gps.length;
        await Future<void>.delayed(const Duration(seconds:6));
        expect(gps.length,count);
      } finally {
        await publisher.stop();
        client.close();
      }
    });
  });
}
