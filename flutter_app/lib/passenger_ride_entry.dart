import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'passenger_demo.dart';
import 'vilnius_evening_backdrop.dart';
import 'brand_logo.dart';
import 'app_language.dart';

/// The first screen after choosing the passenger role.
/// Taxi and transfer are separate entry choices, not a control inside booking.
class PassengerRideEntry extends StatelessWidget {
  const PassengerRideEntry({
    super.key,
    this.enableMapTiles = true,
    required this.tripStore,
    this.onSignOut,
    this.onBackToCabinets,
  });

  final bool enableMapTiles;
  final DemoTripStore tripStore;
  final VoidCallback? onSignOut;
  final VoidCallback? onBackToCabinets;

  void _open(BuildContext context, String type) {
    Navigator.push(context, MaterialPageRoute<void>(
      builder: (_) => PdPassengerLanguageScope(
        child: PassengerDemo(
          enableMapTiles: enableMapTiles,
          tripStore: tripStore,
          initialRideType: type,
        ),
      ),
    ));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('PRIVATE DRIVE · ${pdLabel(context, 'Пассажир')}'),
      leading: onBackToCabinets == null
          ? null
          : BackButton(onPressed: onBackToCabinets),
      actions: [
        const PdLanguageMenu(),
        if (onSignOut != null)
          IconButton(
            key: const Key('passenger-sign-out'),
            tooltip: 'Выйти',
            icon: const Icon(Icons.logout),
            onPressed: onSignOut,
          ),
      ]),
    body: Stack(fit: StackFit.expand, children: [
      const VilniusEveningBackdrop(brightPassenger: true),
      SafeArea(child: Center(child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 460),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: ListView(shrinkWrap: true, children: [
            const Center(
              child: PrivateDriveBrandLogo(
                size: 196, transparentBackground: true)),
            const SizedBox(height: 16),
            Text(pdLabel(context, 'Выбери тип поездки'),
              key: const Key('passenger-entry-title'),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 25, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Card(child: ListTile(
              key: const Key('passenger-entry-taxi'),
              leading: const Icon(Icons.local_taxi, size: 36),
              title: Text(pdLabel(context, 'Такси')),
              subtitle: Text(pdLabel(context, 'Поездка по городу и другие направления')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _open(context, 'Такси'),
            )),
            const SizedBox(height: 12),
            Card(child: ListTile(
              key: const Key('passenger-entry-transfer'),
              leading: const Icon(Icons.directions_car_filled, size: 36),
              title: Text(pdLabel(context, 'Трансфер')),
              subtitle: Text(pdLabel(context, 'Междугородние поездки и аэропорты')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _open(context, 'Трансфер'),
            )),
            const SizedBox(height: 20),
            Text(pdLabel(context, 'Тестовый режим. Реальные заказы и оплата выключены.'),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 12)),
          ]),
      ),
    ))),
    ]),
  );
}
