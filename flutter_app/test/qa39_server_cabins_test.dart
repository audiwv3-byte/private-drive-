import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/native_orders_api.dart';
import '../lib/passenger_ride_entry.dart';
import '../lib/qa_pilot_gps.dart';

void main() {
  const origin='https://qa.invalid';
  const token='synthetic-session-not-valid-on-any-server-000000';
  const id='05cdbc84-0930-4c52-baa1-149a03190d78';
  test('configured HTTPS GPS works without internal QA flags and rejects alternate hosts', () async {
    int calls=0;
    final transport=MockClient((request) async {
      calls++;
      expect(request.url.origin,origin);
      expect(request.followRedirects,false);
      expect(request.headers['Authorization'],'Bearer $token');
      return http.Response('{"available":true}',200);
    });
    final api=NativePilotOrdersApi(baseUrl:origin,token:token,client:transport);
    expect(NativePilotOrdersApi.qaGpsEnabled,false);
    expect(api.gpsEnabled,true);
    await api.publishGps(id,QaGpsFix(54.1,25.1,100),100);
    for(final host in ['https://other.invalid','http://qa.invalid','https://qa.invalid@other.invalid']){
      final invalid=NativePilotOrdersApi(baseUrl:host,token:token,client:transport);
      await expectLater(invalid.publishGps(id,QaGpsFix(54.1,25.1,100),100),throwsFormatException);
    }
    expect(calls,1);
  });
  testWidgets('connected passenger entry offers connected delivery', (tester) async {
    await tester.pumpWidget(MaterialApp(home:PassengerRideEntry(
      ordersApi:NativeOrdersApi(origin,token),tripStore:null,enableMapTiles:false)));
    final delivery=tester.widget<ListTile>(find.byKey(const Key('passenger-entry-delivery')));
    expect(delivery.enabled,true);
    expect(delivery.onTap,isNotNull);
    expect(find.textContaining('Тестовый режим'),findsNothing);
  });
}
