import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:private_drive/demo_dispatcher_cabinet.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/main.dart';
import 'package:private_drive/pilot_cabin.dart';
import 'package:private_drive/pilot_sound_settings.dart';
import 'package:private_drive/remote_sync_demo.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _photo =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPYOTME'
    'AAO1Aac26Q9UAAAAAElFTkSuQmCC';
const _enabled = bool.fromEnvironment('PD_CABINET_SYNC_INTEGRATION');

class _RealHttp extends HttpOverrides {}

/// Preserves real HTTP/JSON/Bearer semantics and can drop a response after
/// SQLite committed it, as on a mobile connection that disappears mid-send.
class _Link extends http.BaseClient {
  _Link(this.zone)
    : _io = zone.run(
        () => IOClient(
          HttpOverrides.runWithHttpOverrides(HttpClient.new, _RealHttp()),
        ),
      );

  final Zone zone;
  final IOClient _io;
  String? token;
  int verifiedSessions = 0;
  bool offline = false;
  bool dropNextMessageAck = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (offline) throw const SocketException('synthetic link down');
    var loseAck = false;
    final response = await zone.run(() async {
      http.Response response;
      try {
        response = await http.Response.fromStream(await _io.send(request));
      } on http.ClientException {
        return null;
      }
      final path = request.url.path;
      if (path == '/native-auth/verify-code' && response.statusCode == 200) {
        token = (jsonDecode(response.body) as Map)['access_token'] as String;
        verifiedSessions++;
      }
      if (dropNextMessageAck &&
          request.method == 'POST' &&
          path.endsWith('/messages')) {
        dropNextMessageAck = false;
        offline = true;
        loseAck = true;
      }
      return response;
    });
    if (loseAck || response == null)
      throw const SocketException('test link interrupted');
    return http.StreamedResponse(
      Stream.value(response.bodyBytes),
      response.statusCode,
      headers: response.headers,
    );
  }

  @override
  void close() => _io.close();
}

void main() {
  late Directory files;
  late Process server;
  late String address;
  late Zone socketZone;

  setUpAll(() async {
    if (!_enabled) return;
    socketZone = Zone.current;
    files = await Directory.systemTemp.createTemp('pd-cabinet-sync-');
    server = await Process.start(
      'python3',
      [
        '../test_sync_server/pd_native_cabinet_mock.py',
        '--test-directory',
        files.path,
      ],
      environment: {'PYTHONPATH': '..:../test_sync_server'},
    );
    server.stderr.drain<void>();
    server.stdout.drain<void>();
    final port = File('${files.path}/port');
    for (var attempt = 0; attempt < 100 && !port.existsSync(); attempt++) {
      await Future<void>.delayed(const Duration(milliseconds: 30));
    }
    address = 'http://127.0.0.1:${port.readAsStringSync()}';
  });

  tearDownAll(() async {
    if (!_enabled) return;
    server.kill();
    await server.exitCode;
    await files.delete(recursive: true);
  });

  testWidgets(
    'main cabinets share a native session-backed order after reconnect',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      await PilotSoundSettings.instance.update(soundEnabled: false);
      await tester.binding.setSurfaceSize(const Size(900, 1100));
      final selected = ValueNotifier(0);
      final links = List.generate(3, (_) => _Link(socketZone));
      final apps = [
        for (final (index, link) in links.indexed)
          PrivateDriveApp(
            key: ValueKey(index),
            mockApiUrl: address,
            httpClient: link,
            enableMapTiles: false,
          ),
      ];
      addTearDown(() async {
        await tester.pumpWidget(const SizedBox.shrink());
        selected.dispose();
        for (final link in links) {
          link.close();
        }
        await tester.binding.setSurfaceSize(null);
      });
      // Offstage devices continue polling their own independent server sessions.
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: ValueListenableBuilder(
            valueListenable: selected,
            builder: (_, int index, _) => Stack(
              children: [
                for (final (i, app) in apps.indexed)
                  Offstage(
                    offstage: i != index,
                    child: TickerMode(enabled: i == index, child: app),
                  ),
              ],
            ),
          ),
        ),
      );

      Finder byKey(String key) => find.byKey(Key(key));

      Future<void> tick() async {
        await tester.pump(const Duration(milliseconds: 250));
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 15)),
        );
        await tester.pump();
      }

      Future<void> until(bool Function() condition, String description) async {
        for (var attempt = 0; attempt < 65; attempt++) {
          if (condition()) return;
          await tick();
        }
        fail('Timed out waiting for $description');
      }

      Future<void> tap(Finder finder, {Finder? scrollable}) async {
        if (finder.evaluate().isEmpty && scrollable != null) {
          await tester.scrollUntilVisible(
            finder,
            280,
            scrollable: scrollable.first,
          );
        }
        await until(() => finder.evaluate().length == 1, finder.toString());
        await tester.ensureVisible(finder);
        await until(
          () => finder.hitTestable().evaluate().length == 1,
          '$finder to be tappable',
        );
        await tester.tap(finder);

        await tick();
        await tick();
      }

      Future<void> select(int index) async {
        selected.value = index;
        await tick();
      }

      Future<void> skipPermissions() async {
        await until(
          () =>
              byKey('permission-onboarding-skip').evaluate().isNotEmpty ||
              byKey('passenger-entry-transfer').evaluate().isNotEmpty ||
              byKey('pilot-power-toggle').evaluate().isNotEmpty ||
              byKey('dispatcher-open-drawer').evaluate().isNotEmpty,
          'first launch',
        );
        if (byKey('permission-onboarding-skip').evaluate().isNotEmpty) {
          await tap(byKey('permission-onboarding-skip'));
        }
      }

      Future<void> signIn(String role, String phone) async {
        await tap(byKey('entry-$role'));
        if (role == 'pilot') await tap(byKey('pilot-identity-notice-sign-in'));
        await tester.enterText(find.byType(TextField).first, '+$phone');
        await tap(byKey('native-legal-acknowledgement'));
        await tap(find.widgetWithText(FilledButton, 'Получить код'));
        final code = File('${files.path}/$phone');
        await until(code.existsSync, 'mock OTP');
        await until(
          () => find.text('Код подтверждения').evaluate().isNotEmpty,
          'OTP input',
        );
        await tester.enterText(
          find.byType(TextField).last,
          code.readAsStringSync(),
        );
        await tick();
        await tap(find.widgetWithText(FilledButton, 'Подтвердить'));
        await until(
          () => links[selected.value].token != null,
          '$role Bearer session',
        );
        await tick();
      }

      await signIn('passenger', '12025550101');
      await skipPermissions();
      await tap(byKey('passenger-entry-transfer'));
      final booking = find.descendant(
        of: byKey('passenger-form'),
        matching: find.byType(Scrollable),
      );
      await tap(byKey('route-airport'), scrollable: booking);
      await tap(byKey('passenger-book-disabled'), scrollable: booking);
      await until(
        () => find.textContaining('Заявка создана').evaluate().isNotEmpty,
        'order confirmation',
      );
      expect(find.byType(RemoteSyncDemo), findsNothing);

      await select(1);
      await signIn('pilot', '12025550102');
      expect(find.byType(PilotCabin), findsNothing);
      final photoResponse = await tester.runAsync(() async {
        final mockTransport = links[1];
        return mockTransport.post(
          Uri.parse('$address/native-identity/submit'),
          headers: {
            'Authorization': 'Bearer ${links[1].token}',
            'Content-Type': 'application/json',
          },
          body: jsonEncode({'photo': _photo}),
        );
      });
      expect(photoResponse?.statusCode, 200);

      await select(2);
      await signIn('dispatcher', '12025550103');
      await skipPermissions();
      await tap(byKey('dispatcher-photo-review'));
      await tap(find.textContaining('Пилот:'));
      await tap(find.widgetWithText(FilledButton, 'Подтвердить'));
      await tester.pageBack();
      await tick();
      var dis = tester
          .widget<DemoDispatcherCabinet>(find.byType(DemoDispatcherCabinet))
          .tripStore;
      expect(dis.pilotLatitude, isNull);

      await select(1);
      await tap(byKey('pilot-identity-notice-acknowledge'));
      await tap(byKey('pilot-identity-notice-continue'));
      await tap(
        byKey('pilot-identity-refresh'),
        scrollable: find.byType(Scrollable).last,
      );
      await skipPermissions();
      var pilot = tester.widget<PilotCabin>(find.byType(PilotCabin)).tripStore!;
      await tap(byKey('pilot-power-toggle'));
      pilot.updatePilotLocation(0, 0);
      expect(pilot.pilotLatitude, isNull);
      pilot.updatePilotLocation(54.7, 25.3);
      await until(() => dis.pilotLatitude == 54.7, 'GPS at dispatcher');

      await select(2);
      expect(find.text('1 пилот с GPS · тестовый сервер'), findsOneWidget);
      final passengerPosition = await tester.runAsync(() async {
        final link = links[0];
        final headers = {
          'Authorization': 'Bearer ${link.token}',
          'Content-Type': 'application/json',
        };
        final current = await link.get(
          Uri.parse('$address/v1/current'), headers: headers);
        final order = jsonDecode(current.body)['trip'] as Map<String, dynamic>;
        return link.post(
          Uri.parse('$address/v1/trips/${order['id']}/passenger-position'),
          headers: headers,
          body: jsonEncode({'latitude': 54.69, 'longitude': 25.27}),
        );
      });
      expect(passengerPosition?.statusCode, 200);
      await until(
        () => dis.dispatcherPassengerLocations.values.contains((54.69, 25.27)),
        'GPS of both pilot and passenger at dispatcher',
      );
      expect(find.textContaining('1 пилот с GPS'), findsOneWidget);
      expect(find.textContaining('Пассажиры с GPS · 1'), findsOneWidget);
      await tap(byKey('dispatcher-open-drawer'));
      await tap(byKey('dispatcher-menu-0'));
      await tap(byKey('dispatcher-assign-pilot'));
      await until(
        () => pilot.status == DemoTripStatus.assigned,
        'assignment at pilot',
      );

      await select(1);
      final offer = byKey('pilot-global-accept-handle');
      if (offer.evaluate().isNotEmpty) {
        await tester.drag(
          offer,
          Offset(
            tester.getSize(byKey('pilot-global-offer-swipe')).width / 2,
            0,
          ),
        );
        await tick();
      } else {
        await tap(byKey('pilot-accept-assigned'));
      }
      await until(() => pilot.pilotAccepted, 'pilot acceptance');

      Future<void> swipeUntil(bool Function() state, String description) async {
        final track = byKey('pilot-next-trip');
        final handle = byKey('pilot-next-trip-handle');
        await until(() => handle.evaluate().isNotEmpty, 'pilot swipe');
        await tester.ensureVisible(handle);
        await until(
          () => handle.hitTestable().evaluate().length == 1,
          "visible pilot swipe handle",
        );
        await tester.drag(handle, Offset(tester.getSize(track).width - 48, 0));
        await until(state, description);
      }

      await swipeUntil(
        () => pilot.status == DemoTripStatus.approaching,
        'pickup leg',
      );
      await swipeUntil(() => pilot.arrivalAt != null, 'pickup arrival');
      await swipeUntil(
        () => pilot.status == DemoTripStatus.underway,
        'trip started',
      );
      await swipeUntil(() => pilot.paused, 'stop');
      await swipeUntil(() => !pilot.paused, 'resume');
      await tap(byKey('pilot-passenger-chat'));
      await tester.enterText(byKey('pilot-chat-input'), 'Synthetic chat');
      links[1].dropNextMessageAck = true;
      await tap(byKey('pilot-chat-send'));
      await until(() => links[1].offline, 'dropped message acknowledgement');
      await until(
        () => dis.pilotChatMessages.length == 1,
        'dispatcher sees message',
      );
      expect(
        tester.widget<TextField>(byKey('pilot-chat-input')).controller!.text,
        'Synthetic chat',
      );
      links[1].offline = false;
      await tap(byKey('pilot-chat-send'));
      await until(
        () => pilot.pilotChatMessages.length == 1,
        'chat restored once',
      );
      expect(dis.pilotChatMessages, ['Synthetic chat']);

      await select(0);
      await tap(byKey('passenger-orders-button'));
      await until(
        () => find.text('Synthetic chat').evaluate().isNotEmpty,
        'passenger sees chat',
      );
      expect(find.text('Synthetic chat'), findsOneWidget);
      await tester.enterText(byKey('passenger-chat-input'), 'Synthetic reply');
      await tap(byKey('passenger-chat-send'));
      await until(
        () => dis.passengerChatMessages.length == 1,
        'dispatcher sees passenger reply',
      );
      await until(
        () => pilot.passengerChatMessages.length == 1,
        'pilot sees passenger reply',
      );
      expect(pilot.passengerChatMessages, ['Synthetic reply']);

      // Dispose each cabinet's store by returning to the role selector.
      // The existing native session should reopen the role and reload the
      // trip and messages from the server into a newly created store.
      Future<void> popRoute(String visibleKey) async {
        final finder = byKey(visibleKey);
        await until(() => finder.evaluate().length == 1, visibleKey);
        Navigator.of(tester.element(finder)).pop();
        await tick();
        await tick();
      }

      await popRoute('passenger-orders-list');
      await popRoute('passenger-orders-button');
      await tap(find.byType(BackButton).hitTestable());
      await tap(byKey('entry-passenger'));
      await skipPermissions();
      await tap(byKey('passenger-entry-transfer'));
      await tap(byKey('passenger-orders-button'));
      Finder orderMessage(String body) => find.descendant(
        of: byKey('passenger-orders-list'),
        matching: find.text(body),
      );
      await until(
        () => orderMessage('Synthetic chat').evaluate().isNotEmpty,
        'passenger reloads trip chat',
      );
      expect(orderMessage('Synthetic chat'), findsOneWidget);
      expect(orderMessage('Synthetic reply'), findsOneWidget);

      await select(2);
      final previousDispatcher = dis;
      await tap(find.byType(BackButton).hitTestable());
      await tap(byKey('entry-dispatcher'));
      await skipPermissions();
      dis = tester
          .widget<DemoDispatcherCabinet>(find.byType(DemoDispatcherCabinet))
          .tripStore;
      expect(dis, isNot(same(previousDispatcher)));
      await until(
        () =>
            dis.status == DemoTripStatus.underway &&
            dis.passengerChatMessages.length == 1,
        'dispatcher reloads trip and chat',
      );
      expect(dis.pilotChatMessages, ['Synthetic chat']);

      await select(1);
      await popRoute('pilot-chat-messages');
      await swipeUntil(
        () => pilot.paused,
        'second stop before leaving the cabin',
      );
      final previousPilot = pilot;
      await popRoute('pilot-next-trip');
      await tap(find.byType(BackButton).hitTestable());
      await tap(byKey('entry-pilot'));
      await tap(byKey('pilot-identity-notice-acknowledge'));
      await tap(byKey('pilot-identity-notice-continue'));
      await tap(
        byKey('pilot-identity-refresh'),
        scrollable: find.byType(Scrollable).last,
      );
      await skipPermissions();
      pilot = tester.widget<PilotCabin>(find.byType(PilotCabin)).tripStore!;
      expect(pilot, isNot(same(previousPilot)));
      await until(
        () => pilot.paused && pilot.passengerChatMessages.length == 1,
        'pilot reloads the active stop and chat',
      );
      expect(pilot.completedStopWaits, hasLength(1));
      expect(pilot.pilotChatMessages, ['Synthetic chat']);
      expect(links.map((link) => link.verifiedSessions), [1, 1, 1]);

      await tap(byKey('pilot-power-toggle'));
      await swipeUntil(() => !pilot.paused, 'resume the restored stop');
      await tap(byKey('pilot-final-destination-mode'));
      await swipeUntil(() => pilot.status == DemoTripStatus.finished, 'finish');
      await until(
        () => dis.status == DemoTripStatus.finished,
        'dispatcher sees finish',
      );

      await select(0);
      await until(
        () => find.textContaining('Поездка завершена').evaluate().isNotEmpty,
        'passenger sees finish',
      );
      expect(find.byType(RemoteSyncDemo), findsNothing);
    },
    skip: !_enabled,
  );
}
