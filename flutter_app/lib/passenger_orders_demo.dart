import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'demo_rating_panel.dart';
import 'app_language.dart';

/// Passenger order controls remain available while navigating between screens.
/// All data is in-memory and disappears on process restart; production persistence
/// needs an authenticated backend.
class PassengerOrdersDemo extends StatefulWidget {
  const PassengerOrdersDemo({super.key, required this.tripStore});
  final DemoTripStore tripStore;

  @override
  State<PassengerOrdersDemo> createState() => _PassengerOrdersDemoState();
}

class _PassengerOrdersDemoState extends State<PassengerOrdersDemo> {
  final _draft = TextEditingController();

  @override
  void dispose() {
    _draft.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(pdLabel(context, 'Мои заказы · PRIVATE DRIVE'))),
    body: AnimatedBuilder(
      animation: widget.tripStore,
      builder: (context, _) {
        final store = widget.tripStore;
        final trip = store.trip;
        if (trip == null) {
          return const Center(child: Text('Заказов в демосессии пока нет',
            key: Key('passenger-orders-empty')));
        }
        final canChat = store.pilotAccepted &&
            (store.status == DemoTripStatus.assigned ||
             store.status == DemoTripStatus.approaching ||
             store.status == DemoTripStatus.underway);
        return ListView(
          key: const Key('passenger-orders-list'),
          padding: const EdgeInsets.all(16),
          children: [
            Card(key: const Key('passenger-order-card'),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(trip.rideType, style: const TextStyle(
                      fontWeight: FontWeight.bold)),
                    Text('${trip.from} → ${trip.to}'),
                    Text(store.statusLabel,
                      key: const Key('passenger-order-status')),
                    Text('${pdLabel(context, 'Оплата')}: ${trip.paymentMethod}'),
                    if (trip.estimatedFareEur != null)
                      Text(
                        trip.extrasRequireQuote
                            ? 'Расчётная часть: ${trip.estimatedFareEur} € · дополнительные услуги по запросу'
                            : 'Предварительная стоимость: ${trip.estimatedFareEur} €',
                        key: const Key('passenger-order-price'),
                      )
                    else
                      const Text(
                        'Стоимость по запросу · диспетчер подтвердит цену до оплаты',
                        key: Key('passenger-order-price'),
                      ),
                    if (store.canPassengerCancel)
                      OutlinedButton.icon(
                        key: const Key('passenger-cancel-order'),
                        icon: const Icon(Icons.cancel_outlined),
                        label: Text(pdLabel(context, 'Отменить заказ')),
                        onPressed: () async {
                          final approved = await showDialog<bool>(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              title: Text(pdLabel(context, 'Отменить заказ?')),
                              content: const Text(
                                'Отменится только тестовая заявка.'),
                              actions: [
                                TextButton(
                                  onPressed: () => Navigator.pop(ctx, false),
                                  child: Text(pdLabel(context, 'Оставить заказ'))),
                                FilledButton(
                                  key: const Key('passenger-confirm-cancel'),
                                  onPressed: () => Navigator.pop(ctx, true),
                                  child: Text(pdLabel(context, 'Подтвердить отмену'))),
                              ],
                            ),
                          );
                          if (approved == true) store.cancelByPassenger();
                        },
                      ),
                    if (!store.canPassengerCancel &&
                        store.status != DemoTripStatus.cancelled)
                      const Text('Отмена через приложение недоступна на '
                        'этом этапе поездки. Обратись к диспетчеру.'),
                    if (store.status == DemoTripStatus.cancelled)
                      Text(pdLabel(context, 'Заявка отменена · демо')),
                  ],
                ),
              ),
            ),
            if (canChat) ...[
              const SizedBox(height: 12),
              Text(pdLabel(context, 'Сообщения пилота'),
                style: TextStyle(fontWeight: FontWeight.bold)),
              if (store.pilotChatMessages.isEmpty)
                Text(pdLabel(context, 'Сообщений от пилота пока нет')),
              for (final message in store.pilotChatMessages)
                ListTile(
                  key: const Key('passenger-pilot-message'),
                  leading: const Icon(Icons.message_outlined),
                  title: Text(message),
                ),
              for (final message in store.passengerChatMessages)
                ListTile(
                  leading: const Icon(Icons.person_outline),
                  title: Text(message),
                ),
              Row(children: [
                Expanded(child: TextField(
                  key: const Key('passenger-chat-input'),
                  controller: _draft,
                  maxLength: 500,
                  decoration: InputDecoration(
                    hintText: pdLabel(context, 'Ответить пилоту'), counterText: ''),
                )),
                IconButton(
                  key: const Key('passenger-chat-send'),
                  icon: const Icon(Icons.send),
                  onPressed: () {
                    if (store.addPassengerChatMessage(_draft.text)) {
                      _draft.clear();
                    }
                  },
                ),
              ]),
              Text(pdLabel(context, 'Локальный чат DEMO: без отправки через интернет.'),
                style: TextStyle(fontSize: 11)),
            ],
            DemoRatingPanel(tripStore: store),
          ],
        );
      },
    ),
  );
}
