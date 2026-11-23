import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:private_drive/native_cabin_entry.dart';
import 'package:private_drive/native_session.dart';
import 'package:private_drive/native_session_manager.dart';
import 'package:private_drive/native_session_vault.dart';
import 'package:private_drive/native_logout_api.dart';
import 'package:private_drive/pilot_identity_api.dart';
import 'package:private_drive/remote_sync_client.dart';

const token='native-ci-bearer-abcdefghijklmnopqrstuvwxyz1234567890';
const base='https://auth.example.test';

class FakeNativeSyncGateway extends RemoteTripGateway {
  FakeNativeSyncGateway(this.cabin, this.calls);
  final String cabin;
  final List<String> calls;
  Map<String,dynamic>? trip;

  @override
  Future<Map<String,dynamic>> get(String path) async {
    calls.add('$cabin GET $path');
    if(path=='/v1/me') return {'demo':true,'role':cabin,'actor':'verified-42'};
    if(path=='/v1/current') return {'trip':trip};
    if(path=='/v1/pilots') return {'pilots':['pilot-verified']};
    if(path.endsWith('/gps')) return {'gps':{'available':false}};
    if(path.contains('/messages?after=')) return {'messages':<Map<String,dynamic>>[]};
    if(path.contains('/events?after=')) return {'events':<Map<String,dynamic>>[]};
    throw StateError('Unexpected $path');
  }

  @override
  Future<Map<String,dynamic>> post(String path, Map<String,dynamic> data) async {
    calls.add('$cabin POST $path');
    if(path=='/v1/trips' && cabin=='passenger') {
      trip={'id':'11111111111111111111111111111111',
        'origin':data['from'],'destination':data['to'],
        'status':'requested','version':1,'paused':0};
      return {'trip':trip};
    }
    throw StateError('Unauthorized mock $path');
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    FlutterSecureStorage.setMockInitialValues({});
  });

  Future<void> launch(WidgetTester tester, String serverRole,
      List<String> calls) async {
    const vault=PdNativeSessionVault();
    await vault.save(PdNativeSession(
      token:token,userId:'verified-42',role:serverRole,
      expiresAt:DateTime.now().add(const Duration(hours:1))));
    final httpClient=MockClient((request) async {
      expect(request.headers['authorization'],'Bearer $token');
      if(request.url.path=='/native-auth/session') {
        return http.Response(jsonEncode({'user_id':'verified-42',
          'role':serverRole,'expires_at':DateTime.now()
              .add(const Duration(minutes:30)).millisecondsSinceEpoch~/1000}),200);
      }
      if(request.url.path=='/native-auth/logout') {
        return http.Response('{"status":"logged_out"}',200);
      }
      return http.Response('{"error":"not_found"}',404);
    });
    addTearDown(httpClient.close);
    await tester.pumpWidget(MaterialApp(home:PdNativeCabinEntry(
      sessionManager:PdNativeSessionManager(
        baseUrl:base,vault:vault,client:httpClient),
      logoutApi:PdNativeLogoutApi(baseUrl:base,client:httpClient),
      isolatedSyncGatewayBuilder:(session,cabin) {
        expect(session.token,token);
        return FakeNativeSyncGateway(cabin,calls);
      },
      signInBuilder:(_,role,onAuthenticated)=>Scaffold(
        body:Text('Phone required: $role')),
      identityApiBuilder:(session)=>PdIdentityApi(
        baseUrl:base,token:session.token,client:httpClient),
    )));
    await tester.pumpAndSettle();
  }

  Future<void> enter(WidgetTester tester,String role) async {
    await tester.tap(find.byKey(Key('entry-$role')));
    await tester.pumpAndSettle();
    final skip=find.byKey(const Key('permission-onboarding-skip'));
    if(skip.evaluate().isNotEmpty) {
      await tester.tap(skip);
      await tester.pumpAndSettle();
    }
  }

  testWidgets('passenger existing cabin opens shared trip API with verified bearer, no manual tokens',
      (tester) async {
    final calls=<String>[];
    await launch(tester,'passenger',calls);
    await enter(tester,'passenger');
    expect(find.byKey(const Key('passenger-entry-taxi')),findsOneWidget);
    expect(find.byKey(const Key('native-cabin-isolated-sync')),findsOneWidget);
    await tester.tap(find.byKey(const Key('native-cabin-isolated-sync')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('remote-token')),findsNothing);
    expect(find.byKey(const Key('remote-server-url')),findsNothing);
    expect(find.byKey(const Key('remote-from')),findsOneWidget);
    await tester.enterText(find.byKey(const Key('remote-from')),'A');
    await tester.enterText(find.byKey(const Key('remote-to')),'B');
    await tester.tap(find.byKey(const Key('remote-create')));
    await tester.pumpAndSettle();
    expect(calls,contains('passenger POST /v1/trips'));
    expect(find.text('Заявка создана · ожидает назначения'),findsOneWidget);
    expect(find.byKey(const Key('remote-assign')),findsNothing);
  });

  testWidgets('dispatcher existing cabin opens remote dispatch with automatic pilot roster',
      (tester) async {
    final calls=<String>[];
    await launch(tester,'dispatcher',calls);
    await enter(tester,'dispatcher');
    expect(find.byKey(const Key('dispatcher-open-drawer')),findsOneWidget);
    await tester.tap(find.byKey(const Key('native-cabin-isolated-sync')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('remote-token')),findsNothing);
    expect(calls,contains('dispatcher GET /v1/current'));
    expect(find.byKey(const Key('remote-create')),findsNothing);
    expect(find.byKey(const Key('remote-pilot-next')),findsNothing);
  });

  testWidgets('passenger cannot open pilot or dispatcher sync by selecting other cabins',
      (tester) async {
    final calls=<String>[];
    await launch(tester,'passenger',calls);
    await enter(tester,'dispatcher');
    expect(find.byKey(const Key('native-cabin-isolated-sync')),findsNothing);
    expect(find.text('Phone required: dispatcher'),findsOneWidget);
    expect(calls,isEmpty);
  });

  test('native gateway attaches same bearer only as Authorization, and cabin as intent',
      () async {
    final requests=<http.Request>[];
    final client=MockClient((request) async {
      requests.add(request);
      return http.Response('{"demo":true,"role":"pilot","actor":"verified-42"}',200);
    });
    final api=RemoteDemoClient('https://isolated.example.test',token,
      cabin:'pilot',httpClient:client);
    final profile=await api.get('/v1/me');
    expect(profile['role'],'pilot');
    expect(requests.single.url.query,isEmpty);
    expect(requests.single.body,isEmpty);
    expect(requests.single.headers['authorization'],'Bearer $token');
    expect(requests.single.headers['x-pd-cabin'],'pilot');
    expect(requests.single.url.toString(),isNot(contains(token)));
    api.close();
  });
}
