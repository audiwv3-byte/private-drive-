import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'passenger_demo.dart';

/// The first screen after choosing the passenger role.
/// Taxi and transfer are separate entry choices, not a control inside booking.
class PassengerRideEntry extends StatelessWidget {
  const PassengerRideEntry({
    super.key,
    this.enableMapTiles = true,
    required this.tripStore,
  });

  final bool enableMapTiles;
  final DemoTripStore tripStore;

  void _open(BuildContext context, String type) {
    Navigator.push(context, MaterialPageRoute<void>(
      builder: (_) => PassengerDemo(
        enableMapTiles: enableMapTiles,
        tripStore: tripStore,
        initialRideType: type,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE · Пассажир')),
    body: SafeArea(child: Center(child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 460),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Выбери тип поездки',
              key: Key('passenger-entry-title'),
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 25, fontWeight: FontWeight.bold)),
            const SizedBox(height: 30),
            Card(child: ListTile(
              key: const Key('passenger-entry-taxi'),
              leading: const Icon(Icons.local_taxi, size: 36),
              title: const Text('Такси'),
              subtitle: const Text('Поездка по городу и другие направления'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _open(context, 'Такси'),
            )),
            const SizedBox(height: 12),
            Card(child: ListTile(
              key: const Key('passenger-entry-transfer'),
              leading: const Icon(Icons.airport_shuttle, size: 36),
              title: const Text('Трансфер'),
              subtitle: const Text('Междугородние поездки и аэропорты'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _open(context, 'Трансфер'),
            )),
            const SizedBox(height: 20),
            const Text('Тестовый режим. Реальные заказы и оплата выключены.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12)),
          ],
        ),
      ),
    ))),
  );
}
