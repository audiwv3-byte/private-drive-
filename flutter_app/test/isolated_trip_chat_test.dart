import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/isolated_trip_chat.dart';
import 'package:private_drive/remote_sync_client.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_orders_demo.dart';
import 'package:private_drive/pilot_passenger_chat_demo.dart';

const firstTripId = '11111111111111111111111111111111';
const nextTripId = '22222222222222222222222222222222';

class SyntheticChatServer {
  String tripId = firstTripId;
  String status = 'assigned';
  final Map<String, List<Map<String, dynamic>>> history = {};
  final Map<String, Map<String, dynamic>> acceptedIds = {};

  RemoteTripGateway role(String name) => SyntheticChatGateway(this, name);

  List<Map<String, dynamic>> get messages =>
      history.putIfAbsent(tripId, () => <Map<String, dynamic>>[]);
}

class SyntheticChatGateway extends RemoteTripGateway {
  SyntheticChatGateway(this.server, this.role);
  final SyntheticChatServer server;
  final String role;

  @override
  Future<Map<String, dynamic>> get(String path) async {
    if (path == '/v1/me') {
      return {'demo': true, 'role': role, 'actor': '${role}_test'};
    }
    if (path == '/v1/current') {
      return {'trip': {
        'id': server.tripId,
        'status': server.status,
        'pilot': 'pilot_test',
      }};
    }
    if (path.contains('/messages?after=')) {
      final after = int.parse(path.split('after=').last);
      return {'messages': server.messages
          .where((item) => (item['seq'] as int) > after).toList()};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<Map<String, dynamic>> post(
      String path, Map<String, dynamic> data) async {
    if (path != '/v1/trips/${server.tripId}/messages') {
      throw StateError('Unexpected POST $path');
    }
    if (!['pilot', 'passenger'].contains(role)) {
      throw StateError('Unexpected role');
    }
    final clientId = data['client_id'] as String;
    final key = '${server.tripId}-$role-$clientId';
    final previous = server.acceptedIds[key];
    if (previous != null) return {'message': previous};
    final message = <String, dynamic>{
      'seq': server.messages.length + 1,
      'role': role,
      'body': data['text'],
      'at': 'test',
    };
    server.messages.add(message);
    server.acceptedIds[key] = message;
    return {'message': message};
  }
}

void main() {
  testWidgets('Passenger and pilot exchange persisted synthetic messages',
      (tester) async {
    final server = SyntheticChatServer();
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: IsolatedTripChat(
        key: const ValueKey('passenger-session'),
        expectedRole: 'passenger',
        gateway: server.role('passenger'),
        pollInterval: const Duration(hours: 1),
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('isolated-chat-trip')), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('isolated-chat-input')), 'Жду у подъезда');
    await tester.tap(find.byKey(const Key('isolated-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages.single['role'], 'passenger');
    expect(server.messages.single['body'], 'Жду у подъезда');

    // Another phone uses a distinct, server-authenticated pilot session.
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: IsolatedTripChat(
        key: const ValueKey('pilot-session'),
        expectedRole: 'pilot',
        gateway: server.role('pilot'),
        pollInterval: const Duration(hours: 1),
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Пассажир: Жду у подъезда'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('isolated-chat-input')), 'Я на месте');
    await tester.tap(find.byKey(const Key('isolated-chat-send')));
    await tester.pumpAndSettle();
    expect(server.messages.length, 2);
    expect(server.messages.last['role'], 'pilot');

    // Passenger reconnects; history comes from the server, not local memory.
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: IsolatedTripChat(
        key: const ValueKey('passenger-reconnected'),
        expectedRole: 'passenger',
        gateway: server.role('passenger'),
        pollInterval: const Duration(hours: 1),
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Пилот: Я на месте'), findsOneWidget);
    expect(find.text('Пассажир: Жду у подъезда'), findsOneWidget);
  });

  testWidgets('Wrong server identity is rejected and cannot send',
      (tester) async {
    final server = SyntheticChatServer();
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: IsolatedTripChat(
        expectedRole: 'pilot',
        gateway: server.role('passenger'),
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('isolated-chat-error')), findsOneWidget);
    expect(find.byKey(const Key('isolated-chat-send')), findsNothing);
    expect(server.messages, isEmpty);
  });

  testWidgets('Switching server trip clears prior conversation',
      (tester) async {
    final server = SyntheticChatServer();
    server.messages.add({
      'seq': 1, 'role': 'pilot', 'body': 'Только старый заказ',
      'at': 'test',
    });
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: IsolatedTripChat(
        expectedRole: 'passenger',
        gateway: server.role('passenger'),
        pollInterval: const Duration(hours: 1),
      ),
    )));
    await tester.pumpAndSettle();
    expect(find.text('Пилот: Только старый заказ'), findsOneWidget);
    server.tripId = nextTripId;
    await tester.tap(find.byKey(const Key('isolated-chat-refresh')));
    await tester.pumpAndSettle();
    expect(find.text('Пилот: Только старый заказ'), findsNothing);
    expect(server.messages, isEmpty);
  });

  testWidgets('Existing cabins expose role-specific remote test chat',
      (tester) async {
    final store = DemoTripStore();
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      home: PassengerOrdersDemo(tripStore: store),
    ));
    expect(find.byKey(const Key('passenger-isolated-chat-panel')),
        findsOneWidget);
    await tester.tap(find.byKey(const Key('passenger-isolated-chat-panel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('isolated-chat-passenger')),
        findsOneWidget);
    await tester.pumpWidget(MaterialApp(
      home: PilotPassengerChatDemo(
        messages: const [], onSend: (_) => false,
      ),
    ));
    await tester.tap(find.byKey(const Key('pilot-isolated-chat-panel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('isolated-chat-pilot')), findsOneWidget);
    expect(find.byKey(const Key('isolated-chat-passenger')), findsNothing);
  });
}
