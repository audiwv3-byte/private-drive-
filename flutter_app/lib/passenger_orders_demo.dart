import 'dart:async';
import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'demo_rating_panel.dart';
import 'app_language.dart';
import 'isolated_trip_chat.dart';
import 'pd_trip_route_editor.dart';

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
  Timer? _waitingRefresh;

  @override
  void initState() {
    super.initState();
    _waitingRefresh = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && widget.tripStore.isWaitingAtPickup) setState(() {});
    });
  }

  @override
  void dispose() {
    _waitingRefresh?.cancel();
    _draft.dispose();
    super.dispose();
  }

  Future<void> _editOrder(DemoTrip trip) async {
    final store = widget.tripStore;
    final changes = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => PdTripRouteEditor(
        origin: trip.from, destination: trip.to, stops: trip.stops,
        pickupLocked: store.arrivalAt != null || store.status == DemoTripStatus.underway,
      ),
    );
    if (!mounted || changes == null) return;
    if (!identical(trip, store.trip) || !store.updateRoute(
      changes['from'] as String, changes['to'] as String, changes['stops'] as List<String>,
    )) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Не удалось изменить маршрут. Проверь адреса и статус заказа.'),
      ));
    }
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
          return ListView(padding: const EdgeInsets.all(16), children: [
            Text(pdLabel(context, 'Заказов в демосессии пока нет'),
              key: const Key('passenger-orders-empty')),
            const Card(child: ExpansionTile(
              key: Key('passenger-isolated-chat-panel'),
              title: Text('Связь между устройствами · тест'),
              children: [Padding(
                padding: EdgeInsets.all(12),
                child: IsolatedTripChat(expectedRole: 'passenger'),
              )],
            )),
          ]);
        }
        final canChat = store.isActive;
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
                    Text(trip.routeLabel),
                    if (store.isActive)
                      OutlinedButton.icon(
                        key: const Key('passenger-edit-order-route'),
                        icon: const Icon(Icons.route_outlined),
                        label: const Text('Изменить маршрут'),
                        onPressed: () => _editOrder(trip),
                      ),
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
                    if (store.arrivalAt != null)
                      Text(
                        store.isWaitingAtPickup
                            ? store.pickupWaitingElapsed() <
                                DemoTripStore.freePickupWaiting
                                ? 'Пилот прибыл · бесплатное ожидание '
                                  'до 3 минут · 0,00 €'
                                : 'Платное ожидание · 0,25 €/мин · '
                                  'сейчас ${store.pickupWaitingFeeLabel()}'
                            : 'Ожидание при посадке · итог '
                              '${store.pickupWaitingFeeLabel()}',
                        key: const Key('passenger-pickup-waiting-fee'),
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
                    hintText: pdLabel(context, 'Написать пилоту и диспетчеру'), counterText: ''),
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
            const Card(child: ExpansionTile(
              key: Key('passenger-isolated-chat-panel'),
              title: Text('Связь между устройствами · тест'),
              children: [Padding(
                padding: EdgeInsets.all(12),
                child: IsolatedTripChat(expectedRole: 'passenger'),
              )],
            )),
            DemoRatingPanel(tripStore: store),
          ],
        );
      },
    ),
  );
}
