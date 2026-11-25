import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class PilotPushQaPage extends StatefulWidget {
  const PilotPushQaPage({super.key});

  @override
  State<PilotPushQaPage> createState() => _PilotPushQaPageState();
}

class _PilotPushQaPageState extends State<PilotPushQaPage> {
  StreamSubscription<RemoteMessage>? _messages;
  StreamSubscription<RemoteMessage>? _openedMessages;
  StreamSubscription<String>? _tokenUpdates;
  String? _token;
  String _status = 'Подготовь телефон к тесту push.';
  bool _connecting = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _connect());
  }

  Future<void> _connect() async {
    if (!mounted || _connecting) return;
    setState(() => _connecting = true);
    try {
      if (Firebase.apps.isEmpty) await Firebase.initializeApp();
      final messaging = FirebaseMessaging.instance;
      final settings = await messaging.requestPermission();
      if (!mounted) return;
      if (settings.authorizationStatus != AuthorizationStatus.authorized &&
          settings.authorizationStatus != AuthorizationStatus.provisional) {
        setState(() => _status = 'Разреши уведомления в настройках телефона.');
        return;
      }

      _messages ??= FirebaseMessaging.onMessage.listen((message) {
        _received(message, 'Push получен в открытом приложении');
      });
      _openedMessages ??= FirebaseMessaging.onMessageOpenedApp.listen((message) {
        _received(message, 'Push открыт из системного уведомления');
      });
      _tokenUpdates ??= messaging.onTokenRefresh.listen((token) {
        if (mounted) setState(() => _token = token);
      });

      final token = await messaging.getToken();
      if (!mounted) return;
      setState(() {
        _token = token;
        _status = token == null
            ? 'Firebase пока не выдал токен. Попробуй ещё раз.'
            : 'Телефон готов принять тестовое уведомление.';
      });
    } on Exception {
      if (mounted) setState(() => _status = 'Связь с Firebase недоступна.');
    } finally {
      if (mounted) setState(() => _connecting = false);
    }
  }

  void _received(RemoteMessage message, String status) {
    if (!mounted) return;
    final title = message.notification?.title;
    setState(() => _status = title == null ? status : '$status · $title');
  }

  @override
  void dispose() {
    _messages?.cancel();
    _openedMessages?.cancel();
    _tokenUpdates?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Тест push-уведомлений')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(_status, key: const Key('pilot-push-status')),
        if (_token != null)
          OutlinedButton.icon(
            onPressed: () async {
              final token = _token;
              if (token == null) return;
              await Clipboard.setData(ClipboardData(text: token));
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Токен скопирован')),
              );
            },
            icon: const Icon(Icons.copy),
            label: const Text('Скопировать токен этого телефона'),
          ),
        if (_token == null)
          OutlinedButton(
            onPressed: _connecting ? null : _connect,
            child: const Text('Проверить подключение'),
          ),
      ],
    ),
  );
}
