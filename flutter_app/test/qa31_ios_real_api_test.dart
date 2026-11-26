import '../lib/qa_pilot_transport.dart';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import '../lib/native_pilot_orders.dart';
import '../lib/pd_http_api.dart';
import '../lib/qa_pilot_gps.dart';

void main() {
  test('QA31 actual Dart GPS API to isolated PostgreSQL fixture', () async {
    const oid=String.fromEnvironment('QA31_ORDER');
    const token='qa-ios-synthetic-pilot-session-not-a-real-credential';
    const finish=bool.fromEnvironment('QA31_FINISH');
    final body=jsonDecode(const String.fromEnvironment('QA31_BODY')) as Map<String,dynamic>;
    final io=HttpClient();
    addTearDown(()=>io.close(force:true));
    final api=QaPilotOrdersApi(baseUrl:QaPilotOrdersApi.qaIosBase,token:token,
      client:MockClient((req) async {
        expect(req.url.scheme,'https'); expect(req.url.host,'qa.invalid');
        expect(req.followRedirects,false);
        final local=Uri.parse('http://127.0.0.1:18729').resolve(req.url.path);
        final out=await io.openUrl(req.method,local);
        out.followRedirects=false;
        req.headers.forEach(out.headers.set);
        out.contentLength=req.bodyBytes.length;
        if(req.bodyBytes.isNotEmpty) out.add(req.bodyBytes);
        final res=await out.close();
        final bytes=await res.expand((x)=>x).toList();
        if(res.statusCode>=400) { print('QA31 local response: ${res.statusCode} ${utf8.decode(bytes)}'); }
        return http.Response.bytes(bytes,res.statusCode);
      }));
    final assigned=await api.load();
    if(finish) {
      expect(assigned.any((x)=>x.orderId==oid),false);
      final stamp=DateTime.now().millisecondsSinceEpoch~/1000;
      await expectLater(api.publishGps(oid,QaGpsFix(1,2,stamp),stamp),throwsA(isA<PdHttpStatusException>().having((e)=>e.statusCode,'status',409)));
    } else {
      expect(assigned.any((x)=>x.orderId==oid),true);
      final stamp=body['captured_at'] as int;
      await api.publishGps(oid,QaGpsFix((body['latitude'] as num).toDouble(),(body['longitude'] as num).toDouble(),stamp),stamp);
    }
  });
}
