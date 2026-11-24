import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/native_closed_invite_api.dart';
import 'package:private_drive/native_session.dart';

class _NoRedirectClient extends http.BaseClient {
  bool called = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    called = true;
    expect(request.followRedirects, isFalse);
    expect(request.url.host, 'private-drive-drbd.onrender.com');
    return http.StreamedResponse(
      Stream<List<int>>.value(utf8.encode('{}')), 307,
      headers: {'location': 'https://example.invalid/untrusted'},
    );
  }
}

void main() {
  final invite = List.filled(43, 'I').join();
  final token = List.filled(64, 'X').join();
  final result = <String, dynamic>{
    'user_id': 'opaque-passenger-account',
    'role': 'passenger',
    'access_token': token,
    'token_type': 'Bearer',
    'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 3600,
  };

  test('invite is never sent to another origin or followed through a redirect',
      () async {
    final client = _NoRedirectClient();
    addTearDown(client.close);
    final wrongOrigin = PdClosedInviteApi(
      baseUrl: 'https://example.invalid', client: client);
    await expectLater(wrongOrigin.redeem(invite), throwsFormatException);
    expect(client.called, isFalse);
    final staging = PdClosedInviteApi(
      baseUrl: PdClosedInviteApi.stagingBaseUrl, client: client);
    await expectLater(staging.redeem(invite), throwsA(isA<Exception>()));
    expect(client.called, isTrue);
  });

  test('client does not accept a staff or expired session from invite response',
      () async {
    for (final patch in [{'role': 'pilot'}, {'expires_at': 1}]) {
      final client = MockClient((_) async =>
        http.Response(jsonEncode({...result, ...patch}), 200));
      addTearDown(client.close);
      final api = PdClosedInviteApi(
        baseUrl: PdClosedInviteApi.stagingBaseUrl, client: client);
      await expectLater(api.redeem(invite), throwsFormatException);
    }
  });

  testWidgets('closed app invite entry is absent by default', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NativeSignInScreen()));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('closed-pilot-invite-field')), findsNothing);
  });

  testWidgets('wrong beta URL cannot fall back to SMS or send an invitation', (tester) async {
    final client = MockClient((_) async => throw StateError('network disabled'));
    addTearDown(client.close);
    await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
      authApiUrl: 'https://example.invalid',
      enableClosedInvite: true,
      httpClient: client,
      onAuthenticated: (_) => throw StateError('cannot authenticate'),
    )));
    await tester.pumpAndSettle();
    final scroll = find.byType(Scrollable).first;
    final button = find.byKey(const Key('closed-pilot-invite-submit'));
    await tester.scrollUntilVisible(button, 120, scrollable: scroll);
    expect(tester.widget<FilledButton>(button).onPressed, isNull);
    expect(find.text('Получить код'), findsNothing);
  });

  testWidgets('used invite clears; a new code opens a session without SMS', (tester) async {
    var attempts = 0;
    final replacement = List.filled(43, 'B').join();
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/native-auth/redeem-invite');
      attempts += 1;
      if (attempts == 1) {
        expect(jsonDecode(request.body), {'invite_code': invite});
        return http.Response('{"error":"invalid_or_expired_invite"}', 401);
      }
      expect(jsonDecode(request.body), {'invite_code': replacement});
      return http.Response(jsonEncode(result), 200);
    });
    addTearDown(client.close);
    final auth = <PdNativeSession>[];
    await tester.pumpWidget(MaterialApp(home: NativeSignInScreen(
      authApiUrl: PdClosedInviteApi.stagingBaseUrl,
      enableClosedInvite: true,
      allowGuestEntry: false,
      httpClient: client,
      onAuthenticated: auth.add,
    )));
    await tester.pumpAndSettle();

    const fieldKey = Key('closed-pilot-invite-field');
    const submitKey = Key('closed-pilot-invite-submit');
    const legalKey = Key('native-legal-acknowledgement');
    final scroll = find.byType(Scrollable).first;
    await tester.scrollUntilVisible(find.byKey(fieldKey), 120, scrollable: scroll);
    expect(tester.widget<TextField>(find.byKey(fieldKey)).obscureText, isTrue);
    await tester.enterText(find.byKey(fieldKey), invite);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(legalKey), 120, scrollable: scroll);
    await tester.tap(find.byKey(legalKey));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(submitKey), 120, scrollable: scroll);
    await tester.tap(find.byKey(submitKey));
    await tester.pumpAndSettle();
    expect(auth, isEmpty);
    expect(tester.widget<FilledButton>(find.byKey(submitKey)).onPressed, isNull);
    await tester.ensureVisible(find.byKey(fieldKey));
    expect(tester.widget<TextField>(find.byKey(fieldKey)).controller!.text, isEmpty);

    await tester.enterText(find.byKey(fieldKey), replacement);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(submitKey));
    await tester.tap(find.byKey(submitKey));
    await tester.pumpAndSettle();

    expect(attempts, 2);
    expect(auth, hasLength(1));
    expect(auth.single.userId, result['user_id']);
    expect(auth.single.token, token);
    expect(auth.single.canPilot || auth.single.canDispatch, isFalse);
    expect(find.text('Получить код'), findsNothing);
    expect(find.text('Телефон подтверждён'), findsNothing);
  });
}
