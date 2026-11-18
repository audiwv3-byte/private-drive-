import 'package:flutter/material.dart';
import 'demo_trip_store.dart';

/// Isolated, in-memory dispatcher demonstration. No production orders,
/// driver assignments, payment mutations, or authentication side effects.
class DemoDispatcherCabinet extends StatelessWidget {
  const DemoDispatcherCabinet({super.key, required this.tripStore});

  final DemoTripStore tripStore;

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE · Диспетчер · DEMO')),
      body: SafeArea(
        child: AnimatedBuilder(
          animation: tripStore,
          builder: (context, _) {
            final trip = tripStore.trip;
            final status = tripStore.status;
            return ListView(
              key: const Key('dispatcher-cabinet'),
              padding: const EdgeInsets.all(18),
              children: [
                const Icon(Icons.support_agent, color: gold, size: 52),
                const SizedBox(height: 8),
                const Text(
                  'КАБИНЕТ ДИСПЕТЧЕРА',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 19, letterSpacing: 1.3,
                    color: gold, fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Тестовая диспетчерская. Нет реальных заказов, '
                  'назначений, платежей или сервера.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                const Text('Заявки', style: TextStyle(
                  fontSize: 18, fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                if (trip == null) const Card(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('Новых тестовых заявок нет',
                      key: Key('dispatcher-empty')),
                  ),
                ),
                if (trip != null)
                  Card(
                    key: const Key('dispatcher-order-card'),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(tripStore.statusLabel,
                            key: const Key('dispatcher-order-status'),
                            style: const TextStyle(
                              color: gold, fontWeight: FontWeight.bold)),
                          const SizedBox(height: 10),
                          Text('Подача: ${trip.from}',
                            key: const Key('dispatcher-pickup')),
                          Text('Назначение: ${trip.to}'),
                          Text('Оплата: ${trip.paymentMethod}'),
                          Text('Дата: ${trip.departure.day}.${trip.departure.month} '
                            '${trip.departure.year} · '
                            '${trip.departure.hour.toString().padLeft(2, '0')}:'
                            '${trip.departure.minute.toString().padLeft(2, '0')}'),
                          if (trip.services.isNotEmpty)
                            Text('Услуги: ${trip.services.join(', ')}'),
                          const SizedBox(height: 12),
                          if (status == DemoTripStatus.requested)
                            FilledButton.icon(
                              key: const Key('dispatcher-assign-pilot'),
                              onPressed: tripStore.assignPilot,
                              icon: const Icon(Icons.assignment_ind_outlined),
                              label: const Text('Назначить тестового пилота'),
                            ),
                          if (status == DemoTripStatus.assigned &&
                              !tripStore.pilotAccepted)
                            const Text('Назначено пилоту · ожидает принятия'),
                          if (status == DemoTripStatus.assigned &&
                              tripStore.pilotAccepted)
                            const Text('Пилот принял заказ'),
                          if (status == DemoTripStatus.finished)
                            const Text('Заказ завершён'),
                        ],
                      ),
                    ),
                  ),
              ],
            );
          },
        ),
      ),
    );
  }
}
