import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import '../lib/native_orders_api.dart';
import '../lib/native_server_cabin.dart';

class _LoopbackHttp extends HttpOverrides {}

class _ObservedClient extends http.BaseClient {
  _ObservedClient(this.transport, this.networkZone);

  final IOClient transport;
  final Zone networkZone;
  final posted = Completer<http.Response>();
  final readHistory = Completer<http.Response>();

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      networkZone.run(() async {
        final streamed = await transport.send(request);
        final response = await http.Response.fromStream(streamed);
        final observed = request.method == 'POST' ? posted : readHistory;
        observed.complete(response);
        return http.StreamedResponse(
          Stream.value(response.bodyBytes),
          response.statusCode,
          headers: response.headers,
        );
      });

  @override
  void close() => transport.close();
}

void main() {
  testWidgets('passenger booking form writes and reads the server order',
      (tester) async {
    const base = String.fromEnvironment('PD_NATIVE_AUTH_API_URL');
    final env = Platform.environment;
    final uri = Uri.parse(base);
    expect(uri.scheme, 'https');
    expect(uri.host, '127.0.0.1');
    final client = (await tester.runAsync(() async {
      final tls = SecurityContext(withTrustedRoots: false)
        ..setTrustedCertificates(env['QA39_CERT']!);
      final transport = _LoopbackHttp().createHttpClient(tls);
      return _ObservedClient(IOClient(transport), Zone.current);
    }))!;
    addTearDown(client.close);

    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(1000, 1000);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
      home: NativeServerCabin(
        enableMapTiles: false,
        ordersApi: NativeOrdersApi(base, env['QA39_PASSENGER_TOKEN']!, client: client),
      ),
    ));

    final entry = find.byKey(const Key('passenger-entry-taxi'));
    await tester.ensureVisible(entry);
    await tester.tap(entry);
    await tester.pumpAndSettle();
    expect(tester.widget<IconButton>(find.byKey(const Key('passenger-orders-button'))).onPressed, isNotNull);
    final from = find.byKey(const Key('passenger-from'));
    final to = find.byKey(const Key('passenger-to'));
    final booking = find.byKey(const Key('passenger-form'));
    final scrollable = find.descendant(of: booking, matching: find.byType(Scrollable)).first;
    await tester.scrollUntilVisible(from, 220, scrollable: scrollable);
    await tester.tap(from);
    await tester.pump();
    await tester.enterText(from, 'Flutter pickup');
    await tester.pump();
    final fromController = tester.widget<TextField>(from).controller!;
    expect(fromController.text, 'Flutter pickup');

    await tester.scrollUntilVisible(to, 110, scrollable: scrollable);
    await tester.tap(to);
    await tester.pump();
    await tester.enterText(to, 'Flutter destination');
    await tester.pump();
    final toController = tester.widget<TextField>(to).controller!;
    expect(toController.text, 'Flutter destination');
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    final send = find.byKey(const Key('passenger-book-disabled'));
    await tester.scrollUntilVisible(send, 300, scrollable: scrollable);
    expect(tester.widget<FilledButton>(send).onPressed, isNotNull,
        reason: 'Booking form held "${fromController.text}" and "${toController.text}"');
    await tester.tap(send);
    final created = (await tester.runAsync(
      () => client.posted.future.timeout(const Duration(seconds: 15)),
    ))!;
    expect(created.statusCode, 201, reason: created.body);
    final id = (jsonDecode(created.body) as Map<String, dynamic>)['order_id'] as String;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    final history = (await tester.runAsync(
      () => client.readHistory.future.timeout(const Duration(seconds: 15)),
    ))!;
    expect(history.statusCode, 200, reason: history.body);
    await tester.pumpAndSettle();
    expect(find.byType(NativeOrdersHistory), findsOneWidget);
    expect(find.text('Flutter pickup → Flutter destination'), findsOneWidget);
    File(env['QA39_NATIVE_ORDER_ID_PATH']!).writeAsStringSync(id);
  });
}
