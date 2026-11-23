import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/remote_sync_client.dart';
import 'package:private_drive/remote_sync_demo.dart';

class FakeDemoServer {
  Map<String, dynamic>? trip;
  int version = 0;
  List<Map<String, dynamic>> events = [];
  List<Map<String, dynamic>> messages = [];
  Map<String, dynamic> gps = {'available': false};
  bool gpsUnavailable = false;

  RemoteTripGateway actor(String role) => FakeGateway(this, role);

  Map<String, dynamic> advance(String status, String event) {
    version++;
    trip = {
      ...?trip,
      'version': version,
      'status': status,
      'paused': event == 'pause' ? 1 : 0,
    };
    events.add({'seq': version, 'version': version, 'event': event});
    return {'trip': trip};
  }
}

class FakeGateway extends RemoteTripGateway {
  FakeGateway(this.server, this.role);
  final FakeDemoServer server;
  final String role;

  @override
  Future<Map<String, dynamic>> get(String path) async {
    if (path == '/v1/me') return {'role': role, 'actor': role + '_test', 'demo': true};
    if (path == '/v1/pilots') return {'pilots': ['pilot_test']};
    if (path == '/v1/current') {
      if (role == 'pilot' && server.trip?['pilot'] != 'pilot_test') {
        return {'trip': null};
      }
      return {'trip': server.trip};
    }
    if (path.endsWith('/gps')) {
      if (server.gpsUnavailable) throw const RemoteDemoException('gps_offline');
      return {'gps': server.gps};
    }
    if (path.contains('/messages?after=')) {
      final after = int.parse(path.split('after=').last);
      return {'messages': server.messages.where((x) =>
        (x['seq'] as int) > after).toList()};
    }
    if (path.contains('/events?after=')) {
      final number = int.parse(path.split('after=').last);
      return {'events': server.events.where((x) => (x['seq'] as int) > number).toList()};
    }
    throw StateError('Unexpected fake route: $path');
  }

  @override
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> data) async {
    if (path.endsWith('/messages') &&
        (role == 'dispatcher' || role == 'passenger' ||
          (role == 'pilot' && server.trip?['pilot'] == 'pilot_test')) &&
        ['requested', 'assigned', 'approaching', 'underway']
            .contains(server.trip?['status'])) {
      final dup = server.messages.where(
        (m) => m['client_id'] == data['client_id'] && m['role'] == role);
      if (dup.isNotEmpty) return {'message': dup.first};
      final message = <String, dynamic>{
        'client_id': data['client_id'],
        'seq': server.messages.length + 1,
        'role': role,
        'body': data['text'],
        'at': 'test',
      };
      server.messages.add(message);
      return {'message': message};
    }
    if (path == '/v1/trips' && role == 'passenger') {
      server.trip = {
        'id': '11111111111111111111111111111111',
        'origin': data['from'],
        'destination': data['to'],
        'pilot': null,
        'status': 'requested',
        'paused': 0,
      };
      return server.advance('requested', 'created');
    }
    if (path.endsWith('/assign') && role == 'dispatcher') {
      server.trip = {...?server.trip, 'pilot': 'pilot_test'};
      return server.advance('assigned', 'assigned');
    }
    if (path.endsWith('/action') && role == 'pilot') {
      final action = data['action'];
      if (action == 'pause') return server.advance(server.trip!['status'] as String, 'pause');
      if (action == 'resume') return server.advance(server.trip!['status'] as String, 'resume');
      final next = switch (server.trip?['status']) {
        'assigned' => 'approaching',
        'approaching' => 'underway',
        'underway' => 'finished',
        _ => throw StateError('Invalid transition'),
      };
      return server.advance(next, 'advance');
    }
    throw StateError('Forbidden fake route: $path');
  }
}

class FlakyChatGateway extends FakeGateway {
  FlakyChatGateway(super.server, super.role);
  bool loseResponse = true;
  @override
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> data) async {
    if (path.endsWith('/messages') && loseResponse) {
      loseResponse = false;
      await super.post(path, data);
      throw const RemoteDemoException('lost response after commit');
    }
    return super.post(path, data);
  }
}

void main() {
  test('Safari map tiles have public HTTPS primary and fallback hosts', () {
    expect(remoteDemoTileTemplate(false),
      'https://tile.openstreetmap.org/{z}/{x}/{y}.png');
    expect(remoteDemoTileTemplate(true),
      'https://tile.openstreetmap.de/{z}/{x}/{y}.png');
    expect(remoteDemoTileTemplate(false).startsWith('https://'), isTrue);
    expect(remoteDemoTileTemplate(true).startsWith('https://'), isTrue);
  });

  test('Voice notification uses latest incoming role, never own message', () {
    final batch = <Map<String, dynamic>>[
      {'seq': 2, 'role': 'pilot', 'body': 'На месте'},
      {'seq': 3, 'role': 'dispatcher', 'body': 'Водитель приехал'},
      {'seq': 4, 'role': 'passenger', 'body': 'Спасибо'},
    ];
    expect(newestIncomingChatRole(batch, 'passenger'), 'dispatcher');
    expect(newestIncomingChatRole(batch, 'pilot'), 'passenger');
    expect(newestIncomingChatRole(batch, 'dispatcher'), 'passenger');
    expect(newestIncomingChatRole([
      {'seq': 5, 'role': 'passenger', 'body': 'Собственный ответ'},
    ], 'passenger'), isNull);
    expect(newestIncomingChatRole(const [], 'pilot'), isNull);
  });

  test('Remote API only allows HTTPS or device-local loopback addresses', () {
    expect(
      () => RemoteDemoClient('http://example.com', List.filled(40, 'x').join()),
      throwsA(isA<RemoteDemoException>()),
    );
    expect(
      () => RemoteDemoClient('https://example.com?token=x', List.filled(40, 'x').join()),
      throwsA(isA<RemoteDemoException>()),
    );
    expect(
      () => RemoteDemoClient('https://example.com', 'short'),
      throwsA(isA<RemoteDemoException>()),
    );
    final client = RemoteDemoClient('https://demo.example.org', List.filled(40, 'x').join());
    client.close();
  });

  testWidgets('Passenger, dispatcher and pilot share test events across screens',
      (tester) async {
    final server = FakeDemoServer();
    const interval = Duration(hours: 1);
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('passenger-initial'),
      gateway: server.actor('passenger'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('remote-from')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('remote-from')), 'Вильнюс');
    await tester.enterText(find.byKey(const Key('remote-to')), 'Каунас');
    await tester.tap(find.byKey(const Key('remote-create')));
    await tester.pumpAndSettle();
    expect(find.text('Заявка создана · ожидает назначения'), findsOneWidget);
    expect(server.trip!['origin'], 'Вильнюс');

    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('dispatcher'),
      gateway: server.actor('dispatcher'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('remote-assign')), findsOneWidget);
    expect(find.byKey(const Key('remote-pilot-next')), findsNothing);
    await tester.tap(find.byKey(const Key('remote-assign')));
    await tester.pumpAndSettle();
    expect(server.trip!['status'], 'assigned');

    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('pilot'),
      gateway: server.actor('pilot'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('remote-pilot-map')), findsOneWidget);
    expect(find.text('Демо-диспетчер'), findsNothing);
    expect(find.byKey(const Key('remote-from')), findsNothing);
    await tester.tap(find.byKey(const Key('remote-pilot-next')));
    await tester.pumpAndSettle();
    expect(find.text('Пилот едет к пассажиру'), findsOneWidget);
    await tester.tap(find.byKey(const Key('remote-pilot-pause')));
    await tester.pumpAndSettle();
    expect(find.text('Остановка · демо'), findsOneWidget);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('remote-pilot-next'))).onPressed, isNull);
    await tester.tap(find.byKey(const Key('remote-pilot-pause')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('remote-pilot-next')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('remote-pilot-next')));
    await tester.pumpAndSettle();
    expect(server.trip!['status'], 'finished');

    // New widget simulates app restart: same server, new client session.
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('passenger-restart'),
      gateway: server.actor('passenger'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.text('Поездка завершена · демо'), findsOneWidget);
    expect(find.byKey(const Key('remote-trip-route')), findsOneWidget);
    expect(find.text('Наличные'), findsNothing);
  });

  testWidgets('Unassigned pilot sees neither booking nor dispatcher controls',
      (tester) async {
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      gateway: FakeDemoServer().actor('pilot'),
      enableMapTiles: false, pollInterval: const Duration(hours: 1),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Нет тестового заказа'), findsOneWidget);
    expect(tester.widget<FilledButton>(
      find.byKey(const Key('remote-pilot-next'))).onPressed, isNull);
    expect(find.byKey(const Key('remote-assign')), findsNothing);
    expect(find.byKey(const Key('remote-create')), findsNothing);
  });
  testWidgets('Pilot and passenger exchange messages across separate remote sessions',
      (tester) async {
    final server = FakeDemoServer();
    server.trip = {
      'id': '11111111111111111111111111111111',
      'origin': 'Вильнюс', 'destination': 'Каунас',
      'pilot': 'pilot_test', 'status': 'assigned',
      'paused': 0, 'version': 2,
    };
    const interval = Duration(hours: 1);
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('remote-pilot-chat'),
      gateway: server.actor('pilot'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('remote-chat-input')), 'Я у входа');
    await tester.tap(find.byKey(const Key('remote-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages.single['body'], 'Я у входа');

    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('remote-passenger-chat'),
      gateway: server.actor('passenger'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.text('Пилот: Я у входа'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('remote-chat-input')), 'Выхожу');
    await tester.tap(find.byKey(const Key('remote-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages.length, 2);

    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('remote-pilot-again'),
      gateway: server.actor('pilot'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.text('Пассажир: Выхожу'), findsOneWidget);

    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      key: const ValueKey('remote-dispatcher-no-chat'),
      gateway: server.actor('dispatcher'),
      enableMapTiles: false, pollInterval: interval,
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('remote-chat-input')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('remote-chat-input')),
      'Диспетчер на связи');
    await tester.tap(find.byKey(const Key('remote-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages.last['role'], 'dispatcher');
  });

  testWidgets('Remote chat announces only new opposite-role messages once',
      (tester) async {
    final server = FakeDemoServer();
    server.trip = {
      'id': '11111111111111111111111111111111',
      'origin': 'Вильнюс', 'destination': 'Каунас',
      'pilot': 'pilot_test', 'status': 'assigned',
      'paused': 0, 'version': 2,
    };
    server.messages.add({'seq': 1, 'role': 'pilot',
      'body': 'Старое сообщение', 'at': 'test'});
    var alerts = 0;
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      gateway: server.actor('passenger'),
      enableMapTiles: false,
      pollInterval: const Duration(hours: 1),
      onIncomingMessageVoice: () => alerts++,
    )));
    await tester.pumpAndSettle();
    expect(alerts, 0); // History is not announced on session start.
    server.messages.add({'seq': 2, 'role': 'pilot',
      'body': 'Новое сообщение', 'at': 'test'});
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(alerts, 1);
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(alerts, 1); // Cursor protects against duplicates.
    server.messages.add({'seq': 3, 'role': 'passenger',
      'body': 'Ответ пилота', 'at': 'test'});
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(alerts, 1); // Own sends do not announce.
    server.messages.add({'seq': 4, 'role': 'pilot',
      'body': 'Второе входящее', 'at': 'test'});
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(alerts, 2);
  });


  testWidgets('lost response reuses chat client_id and never duplicates',
      (tester) async {
    final server=FakeDemoServer();
    server.trip={
      'id':'11111111111111111111111111111111',
      'origin':'Test A','destination':'Test B',
      'pilot':'pilot_test','status':'assigned','paused':0,'version':2,
    };
    final gateway=FlakyChatGateway(server,'passenger');
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      gateway:gateway,enableMapTiles:false,
      pollInterval:const Duration(hours:1),
    )));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('remote-chat-input')),'Проверка');
    await tester.tap(find.byKey(const Key('remote-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages,hasLength(1));
    await tester.tap(find.byKey(const Key('remote-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages,hasLength(1));
    expect(find.text('Пассажир: Проверка'),findsOneWidget);
  });

  testWidgets('dispatcher GPS is shown only from valid server fix and hidden on outage',
      (tester) async {
    final server = FakeDemoServer();
    server.trip = {
      'id':'11111111111111111111111111111111',
      'origin':'Test A','destination':'Test B',
      'pilot':'pilot_test','status':'assigned','paused':0,'version':2,
    };
    await tester.pumpWidget(MaterialApp(home: RemoteSyncDemo(
      gateway:server.actor('dispatcher'), enableMapTiles:false,
      pollInterval:const Duration(hours:1),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Подтверждённых GPS-точек нет'),findsOneWidget);
    server.gps={'available':true,'latitude':54.6872,'longitude':25.2797};
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(find.text('GPS пилота подтверждён · тест'),findsOneWidget);
    server.gpsUnavailable=true;
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(find.text('Подтверждённых GPS-точек нет'),findsOneWidget);
    expect(find.byKey(const Key('remote-trip-route')),findsOneWidget,
      reason:'GPS outage must not prevent trip refresh');
    server.gpsUnavailable=false;
    server.gps={'available':true,'latitude':999,'longitude':25.2797};
    await tester.tap(find.byKey(const Key('remote-refresh')));
    await tester.pumpAndSettle();
    expect(find.text('Подтверждённых GPS-точек нет'),findsOneWidget);
  });

}
