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
          return Center(child: Text(pdLabel(context, 'Заказов в демосессии пока нет'),
            key: const Key('passenger-orders-empty')));
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
                    Text(pdLabel(context, trip.rideType), style: const TextStyle(
                      fontWeight: FontWeight.bold)),
                    Text('${trip.from} → ${trip.to}'),
                    Text(pdLabel(context, store.statusLabel),
                      key: const Key('passenger-order-status')),
                    Text('${pdLabel(context, 'Оплата')}: ${pdLabel(context, trip.paymentMethod)}'),
                    if (trip.estimatedFareEur != null)
                      Text(
                        trip.extrasRequireQuote
                            ? pdTr(context,
                                'Расчётная часть: ${trip.estimatedFareEur} € · дополнительные услуги по запросу',
                                'Apskaičiuota dalis: ${trip.estimatedFareEur} € · papildomos paslaugos pagal užklausą',
                                'Estimated portion: €${trip.estimatedFareEur} · extras on request')
                            : pdTr(context,
                                'Предварительная стоимость: ${trip.estimatedFareEur} €',
                                'Preliminari kaina: ${trip.estimatedFareEur} €',
                                'Estimated fare: €${trip.estimatedFareEur}'),
                        key: const Key('passenger-order-price'),
                      )
                    else
                      Text(
                        pdLabel(context, 'Стоимость по запросу · диспетчер подтвердит цену до оплаты'),
                        key: const Key('passenger-order-price'),
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
                              content: Text(pdLabel(context, 'Отменится только тестовая заявка.')),
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
                      Text(pdLabel(context, 'Отмена через приложение недоступна на этом этапе поездки. Обратись к диспетчеру.')),
                    if (store.status == DemoTripStatus.cancelled)
                      Text(pdLabel(context, 'Заявка отменена · демо')),
                  ],
                ),
              ),
            ),
            if (canChat) ...[
              const SizedBox(height: 12),
              Text(pdLabel(context, 'Чат заказа: пилот и диспетчер'),
                style: TextStyle(fontWeight: FontWeight.bold)),
              if (store.pilotChatMessages.isEmpty)
                if (store.dispatcherChatMessages.isEmpty)
                  Text(pdLabel(context, 'Сообщений от пилота пока нет')),
              for (final message in store.pilotChatMessages)
                ListTile(
                  key: const Key('passenger-pilot-message'),
                  leading: const Icon(Icons.message_outlined),
                  title: Text(message),
                ),
              for (final message in store.dispatcherChatMessages)
                ListTile(
                  key: const Key('passenger-dispatcher-message'),
                  leading: const Icon(Icons.support_agent),
                  title: Text('Диспетчер: $message'),
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
