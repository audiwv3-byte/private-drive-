import 'dart:async';

import 'package:flutter/material.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:permission_handler/permission_handler.dart';

import 'remote_sync_client.dart';

class PdTripVoice extends StatefulWidget {
  const PdTripVoice({
    super.key,
    required this.gateway,
    required this.tripId,
    required this.role,
  });

  final RemoteTripGateway gateway;
  final String tripId;
  final String role;

  @override
  State<PdTripVoice> createState() => _PdTripVoiceState();
}

class _PdTripVoiceState extends State<PdTripVoice>
    with AutomaticKeepAliveClientMixin<PdTripVoice> {
  Room? _room;
  Timer? _timer;
  Map<String, dynamic>? _call;
  bool _busy = false;
  String? _error;

  String get _path => '/v1/trips/${widget.tripId}/voice';

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    unawaited(_update());
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _update());
  }

  Future<void> _update([String? action]) async {
    if (_busy) return;
    setState(() => _busy = true);
    final callId = _call?['id'];
    final gateway = widget.gateway;
    final path = _path;
    try {
      if (action == 'accept') {
        final status = await Permission.microphone.request();
        if (!mounted) return;
        if (!status.isGranted) {
          setState(() => _error = 'Разреши микрофон, чтобы принять звонок.');
          return;
        }
      }
      final result = action == null
          ? await gateway.get(path)
          : await gateway.post(path, {
              'action': action,
              if (callId != null) 'id': callId,
            });
      if (!mounted) {
        if ((action, result['call']) case ('invite', {'id': final String id})) {
          unawaited(_endRemote(gateway, path, id));
        }
        return;
      }
      setState(() {
        _call = result['call'] as Map<String, dynamic>?;
        _error = null;
      });
      if (_call?['state'] == 'accepted' && _room == null) {
        final id = _call!['id'] as String;
        try {
          await _connect(id);
        } catch (_) {
          await _endRemote(gateway, path, id);
          rethrow;
        }
      } else if (_call == null) {
        await _disconnect();
      }
    } catch (_) {
      if (mounted)
        setState(() => _error = 'Не удалось подключить голосовую связь.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _connect(String id) async {
    final allowed = await Permission.microphone.request();
    if (!mounted) return;
    if (!allowed.isGranted) throw StateError('Microphone permission denied');
    final credentials = await widget.gateway.post(_path, {
      'action': 'join',
      'id': id,
    });
    if (!mounted) return;
    final url = credentials['url'] as String;
    final endpoint = Uri.parse(url);
    if (endpoint.scheme != 'wss' ||
        endpoint.host.isEmpty ||
        endpoint.userInfo.isNotEmpty) {
      throw const FormatException('Invalid voice endpoint');
    }
    final room = Room();
    _room = room;
    try {
      await room.connect(url, credentials['token'] as String);
      if (!mounted || !identical(_room, room)) return;
      final local = room.localParticipant;
      if (local == null) throw StateError('Missing local participant');
      await local.setMicrophoneEnabled(true);
    } catch (_) {
      if (identical(_room, room)) await _disconnect();
      rethrow;
    }
  }

  Future<void> _disconnect() async {
    final room = _room;
    _room = null;
    if (room == null) return;
    try {
      await room.disconnect();
    } catch (_) {
      // Disposing the room still releases the microphone after a network error.
    } finally {
      await room.dispose();
    }
  }

  Future<void> _endRemote(
    RemoteTripGateway gateway,
    String path,
    Object id,
  ) async {
    try {
      await gateway.post(path, {'action': 'end', 'id': id});
    } catch (_) {
      // The local media connection closes independently of the API response.
    }
  }

  void _hangUp() {
    unawaited(_disconnect());
    unawaited(_update('end'));
  }

  @override
  void dispose() {
    _timer?.cancel();
    final id = _call?['id'];
    if (id != null) unawaited(_endRemote(widget.gateway, _path, id));
    unawaited(_disconnect());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final incoming =
        _call != null &&
        _call?['caller'] != widget.role &&
        _call?['state'] == 'ringing';
    return Wrap(
      spacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        if (_call == null)
          TextButton.icon(
            key: const Key('trip-voice-call'),
            onPressed: _busy ? null : () => _update('invite'),
            icon: const Icon(Icons.call_outlined),
            label: const Text('Позвонить через интернет'),
          )
        else ...[
          Text(
            incoming
                ? 'Входящий звонок'
                : (_call?['state'] == 'accepted'
                      ? 'Голосовой вызов'
                      : 'Вызов…'),
          ),
          if (incoming)
            TextButton(
              onPressed: _busy ? null : () => _update('accept'),
              child: const Text('Принять'),
            ),
          TextButton(
            onPressed: _busy ? null : _hangUp,
            child: Text(incoming ? 'Отклонить' : 'Завершить'),
          ),
        ],
        if (_error case final String error) Text(error),
      ],
    );
  }
}
