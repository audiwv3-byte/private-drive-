import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import 'remote_sync_client.dart';

/// Explicit opt-in isolated server chat. Never binds a local DEMO order to a
/// remote trip: the server resolves its own per-user current trip.
class IsolatedTripChat extends StatefulWidget {
  const IsolatedTripChat({
    super.key,
    required this.expectedRole,
    this.gateway,
    this.pollInterval = const Duration(seconds: 3),
  }) : assert(expectedRole == 'passenger' || expectedRole == 'pilot');

  final String expectedRole;
  final RemoteTripGateway? gateway;
  final Duration pollInterval;

  @override
  State<IsolatedTripChat> createState() => _IsolatedTripChatState();
}

class _IsolatedTripChatState extends State<IsolatedTripChat> {
  final _url = TextEditingController();
  final _token = TextEditingController();
  final _draft = TextEditingController();
  final _random = Random.secure();

  RemoteTripGateway? _api;
  Timer? _timer;
  bool _owned = false, _connecting = false, _refreshing = false;
  bool _sending = false;
  String? _tripId, _pendingId, _pendingText;
  String _status = '', _error = '';
  int _cursor = 0;
  final _messages = <Map<String, dynamic>>[];

  @override
  void initState() {
    super.initState();
    if (widget.gateway != null) {
      // A fake gateway may be injected only by isolated widget tests.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _connect(widget.gateway!, owned: false);
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    if (_owned) _api?.close();
    _url.dispose();
    _token.dispose();
    _draft.dispose();
    super.dispose();
  }

  String _clientId() => List.generate(
    16, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<void> _connect(RemoteTripGateway candidate,
      {required bool owned}) async {
    if (_connecting || _api != null) return;
    setState(() { _connecting = true; _error = ''; });
    try {
      final profile = await candidate.get('/v1/me');
      if (profile['demo'] != true ||
          profile['role'] != widget.expectedRole ||
          profile['actor'] is! String ||
          (profile['actor'] as String).isEmpty) {
        throw const RemoteDemoException(
          'Тестовый токен не соответствует роли этого кабинета');
      }
      // The server owns order identity, never a caller-supplied/local order.
      final current = await candidate.get('/v1/current');
      final remote = current['trip'];
      if (remote != null && remote is! Map<String, dynamic>) {
        throw const RemoteDemoException('Некорректный заказ на тестовом сервере');
      }
      if (!mounted) { if (owned) candidate.close(); return; }
      _api = candidate;
      _owned = owned;
      _token.clear(); // Never persist or display secrets.
      _timer?.cancel();
      _timer = Timer.periodic(widget.pollInterval, (_) => _refresh());
      await _refresh();
    } on Exception catch (e) {
      if (owned) candidate.close();
      if (mounted) setState(() { _error = e.toString(); });
    } finally {
      if (mounted) setState(() { _connecting = false; });
    }
  }

  void _connectFromFields() {
    RemoteDemoClient client;
    try {
      client = RemoteDemoClient(_url.text, _token.text);
    } on Exception catch (e) {
      setState(() { _error = e.toString(); });
      return;
    }
    _token.clear();
    _connect(client, owned: true);
  }

  Future<void> _refresh() async {
    final api = _api;
    if (api == null || _refreshing) return;
    _refreshing = true;
    try {
      final current = await api.get('/v1/current');
      final rawTrip = current['trip'];
      if (rawTrip != null && rawTrip is! Map<String, dynamic>) {
        throw const RemoteDemoException('Некорректный ответ о заказе');
      }
      final trip = rawTrip as Map<String, dynamic>?;
      final rawId = trip?['id'];
      final id = rawId is String && RegExp(r'^[a-f0-9]{32}$').hasMatch(rawId)
          ? rawId : null;
      if (trip != null && id == null) {
        throw const RemoteDemoException('Неверный идентификатор тестового заказа');
      }
      if (id != _tripId) {
        _tripId = id;
        _messages.clear();
        _cursor = 0;
        _pendingId = null;
        _pendingText = null;
      }
      final status = trip?['status'];
      _status = status is String ? status : '';
      if (id != null) {
        final response = await api.get('/v1/trips/$id/messages?after=$_cursor');
        final rows = response['messages'];
        if (rows is! List) {
          throw const RemoteDemoException('Некорректная история сообщений');
        }
        // Validate the entire batch before advancing the pagination cursor:
        // a malformed trailing row must never hide earlier valid messages.
        final received = <Map<String, dynamic>>[];
        var nextCursor = _cursor;
        for (final row in rows) {
          if (row is! Map<String, dynamic> ||
              row['seq'] is! int || row['seq'] <= 0 ||
              row['role'] is! String ||
              !['pilot', 'passenger', 'dispatcher'].contains(row['role']) ||
              row['body'] is! String) {
            throw const RemoteDemoException('Некорректное сообщение сервера');
          }
          final number = row['seq'] as int;
          if (number > nextCursor) {
            received.add(row);
            nextCursor = number;
          }
        }
        _messages.addAll(received);
        _cursor = nextCursor;
        // Keep a bounded screen buffer; the authoritative history is on server.
        if (_messages.length > 100) {
          _messages.removeRange(0, _messages.length - 100);
        }
      }
      if (mounted) setState(() { _error = ''; });
    } on Exception catch (e) {
      if (mounted) setState(() { _error = e.toString(); });
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _send() async {
    final api = _api;
    final id = _tripId;
    final text = _draft.text.trim();
    if (api == null || id == null || _sending ||
        text.isEmpty || text.length > 500 ||
        !['requested', 'assigned', 'approaching', 'underway']
            .contains(_status)) return;
    _pendingId = _pendingText == text ? (_pendingId ?? _clientId()) : _clientId();
    _pendingText = text;
    setState(() { _sending = true; _error = ''; });
    try {
      await api.post('/v1/trips/$id/messages', {
        'client_id': _pendingId,
        'text': text,
      });
      _draft.clear();
      _pendingId = null;
      _pendingText = null;
    } on Exception catch (e) {
      if (mounted) setState(() { _error = e.toString(); });
    } finally {
      if (mounted) setState(() { _sending = false; });
    }
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final connected = _api != null;
    final canWrite = connected && _tripId != null &&
        ['requested', 'assigned', 'approaching', 'underway']
            .contains(_status);
    final senderNames = {
      'pilot': 'Пилот',
      'passenger': 'Пассажир',
      'dispatcher': 'Диспетчер',
    };
    return Column(
      key: Key('isolated-chat-${widget.expectedRole}'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text('Только отдельный тестовый сервер. '
            'Это не переписка локального DEMO-заказа.',
          style: TextStyle(fontSize: 12)),
        if (!connected) ...[
          if (widget.gateway == null) ...[
            TextField(
              key: const Key('isolated-chat-url'),
              controller: _url,
              decoration: const InputDecoration(
                labelText: 'HTTPS-адрес изолированного тестового сервера'),
            ),
            TextField(
              key: const Key('isolated-chat-token'),
              controller: _token,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              decoration: const InputDecoration(labelText: 'Тестовый токен роли'),
            ),
            TextButton(
              key: const Key('isolated-chat-connect'),
              onPressed: _connecting ? null : _connectFromFields,
              child: const Text('Подключить тестовый чат'),
            ),
          ],
          if (_connecting) const LinearProgressIndicator(),
        ] else ...[
          if (_tripId == null)
            const Text('На тестовом сервере нет доступного заказа. '
                'Реальные заказы здесь не создаются.')
          else ...[
            Text('Тестовый заказ: ${_tripId!.substring(0, 8)}…',
              key: const Key('isolated-chat-trip')),
            SizedBox(
              height: 180,
              child: ListView(
                key: const Key('isolated-chat-messages'),
                children: [
                  for (final message in _messages)
                    ListTile(
                      dense: true,
                      key: Key('isolated-message-${message['seq']}'),
                      title: Text(
                        '${senderNames[message['role']] ?? 'Участник'}: '
                        '${message['body']}'),
                    ),
                ],
              ),
            ),
            if (canWrite)
              Row(children: [
                Expanded(child: TextField(
                  key: const Key('isolated-chat-input'),
                  controller: _draft,
                  maxLength: 500,
                  decoration: const InputDecoration(
                    hintText: 'Сообщение тестового заказа', counterText: ''),
                )),
                IconButton(
                  key: const Key('isolated-chat-send'),
                  onPressed: _sending ? null : _send,
                  icon: const Icon(Icons.send),
                ),
              ]),
          ],
          TextButton.icon(
            key: const Key('isolated-chat-refresh'),
            onPressed: _refreshing ? null : _refresh,
            icon: const Icon(Icons.refresh),
            label: const Text('Обновить сообщения'),
          ),
        ],
        if (_error.isNotEmpty)
          Text(_error, key: const Key('isolated-chat-error'),
            style: const TextStyle(color: Colors.orangeAccent)),
      ],
    );
  }
}
