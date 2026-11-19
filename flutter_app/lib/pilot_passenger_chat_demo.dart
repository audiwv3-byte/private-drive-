import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'app_language.dart';

/// Pilot-only offline chat preview. No APIs, SMS, phone calls or persistence.
/// The demo has no verified passenger contact details.
class PilotPassengerChatDemo extends StatefulWidget {
  const PilotPassengerChatDemo({
    super.key,
    required this.messages,
    required this.onSend,
    this.tripStore,
  });

  final List<String> messages;
  final bool Function(String) onSend;
  final DemoTripStore? tripStore;

  @override
  State<PilotPassengerChatDemo> createState() => _PilotPassengerChatDemoState();
}

class _PilotPassengerChatDemoState extends State<PilotPassengerChatDemo> {
  final _draft = TextEditingController();
  late final List<String> _visibleMessages;

  @override
  void initState() {
    super.initState();
    _visibleMessages = List<String>.of(widget.messages);
    widget.tripStore?.addListener(_refreshMessages);
  }

  void _refreshMessages() {
    if (!mounted || widget.tripStore == null) return;
    final store = widget.tripStore!;
    setState(() {
      _visibleMessages
        ..clear()
        ..addAll(store.pilotChatMessages)
        ..addAll(store.passengerChatMessages.map((m) => 'Пассажир: $m'))
        ..addAll(store.dispatcherChatMessages.map((m) => 'Диспетчер: $m'));
    });
  }

  @override
  void dispose() {
    widget.tripStore?.removeListener(_refreshMessages);
    _draft.dispose();
    super.dispose();
  }

  void _send([String? quickReply]) {
    final value = (quickReply ?? _draft.text).trim();
    if (value.isEmpty) return;
    if (!widget.onSend(value)) return;
    _draft.clear();
    if (widget.tripStore == null) {
      setState(() => _visibleMessages.add(value));
    }
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    return Scaffold(
      appBar: AppBar(
        title: Text(pdLabel(context, 'Пассажир · демо')),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                pdLabel(context, 'Локальный чат DEMO: сообщения доступны пассажиру в этом приложении, но не передаются между телефонами.'),
                textAlign: TextAlign.center,
                style: const TextStyle(color: gold),
              ),
            ),
            Expanded(
              child: ListView(
                key: const Key('pilot-chat-messages'),
                padding: const EdgeInsets.all(16),
                children: [
                  for (final message in _visibleMessages)
                    Align(
                      alignment: Alignment.centerRight,
                      child: Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: const Color(0xFF3A3020),
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text(message.startsWith('Пассажир: ')
                               ? '${pdLabel(context, 'Пассажир')}: ${message.substring('Пассажир: '.length)}'
                               : message),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            SizedBox(
              height: 48,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                children: [
                  for (final reply in ['Я на месте', 'Понятно', 'Я уже в пути'])
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: ActionChip(
                        label: Text(pdLabel(context, reply)),
                        onPressed: () => _send(reply),
                      ),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      key: const Key('pilot-chat-input'),
                      controller: _draft,
                      maxLength: 500,
                      onChanged: (_) => setState(() {}),
                      decoration: InputDecoration(
                        hintText: pdLabel(context, 'Введите сообщение'),
                        border: OutlineInputBorder(),
                        counterText: '',
                      ),
                    ),
                  ),
                  IconButton.filled(
                    key: const Key('pilot-chat-send'),
                    tooltip: pdLabel(context, 'Отправить в демочат'),
                    onPressed: () => _send(),
                    icon: const Icon(Icons.send),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
