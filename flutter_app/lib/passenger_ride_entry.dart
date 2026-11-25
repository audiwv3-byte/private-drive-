import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'passenger_demo.dart';
import 'passenger_extra_services.dart';
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

  void _open(BuildContext context, String type, {bool advanceBooking = false,
      DateTime? advanceDate, TimeOfDay? advanceTime}) {
    Navigator.push(context, MaterialPageRoute<void>(
      builder: (_) => PdPassengerLanguageScope(
        child: PassengerDemo(
          enableMapTiles: enableMapTiles,
          tripStore: tripStore,
          initialRideType: type,
          initialAdvanceBooking: advanceBooking,
          initialAdvanceDate: advanceDate,
          initialAdvanceTime: advanceTime,
        ),
      ),
    ));
  }

  /// Advance booking is available for both ride types. Pick date/time before
  /// opening the address and trip details form.
  Future<void> _startAdvanceBooking(BuildContext context) async {
    final type = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(pdTr(context, 'Что бронируем заранее?',
                'Ką rezervuojate iš anksto?', 'What would you like to book?'),
              style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            ListTile(
              key: const Key('advance-choose-taxi'),
              leading: const Icon(Icons.local_taxi),
              title: Text(pdLabel(context, 'Такси')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.pop(sheetContext, 'Такси'),
            ),
            ListTile(
              key: const Key('advance-choose-transfer'),
              leading: const Icon(Icons.directions_car_filled),
              title: Text(pdLabel(context, 'Трансфер')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.pop(sheetContext, 'Трансфер'),
            ),
          ]),
        ),
      ),
    );
    if (type == null || !context.mounted) return;
    final now = DateTime.now();
    final selectedDate = await showDatePicker(
      context: context,
      initialDate: DateUtils.dateOnly(now),
      firstDate: DateUtils.dateOnly(now),
      lastDate: DateUtils.dateOnly(now).add(const Duration(days: 365)),
      helpText: pdTr(context, 'Дата предварительного заказа',
          'Išankstinio užsakymo data', 'Advance booking date'),
    );
    if (selectedDate == null || !context.mounted) return;
    final selectedTime = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(now),
      helpText: pdTr(context, 'Время подачи',
          'Paėmimo laikas', 'Pickup time'),
    );
    if (selectedTime == null || !context.mounted) return;
    _open(context, type, advanceBooking: true,
      advanceDate: selectedDate, advanceTime: selectedTime);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('PRIVATE DRIVE · ${pdLabel(context, 'Пассажир')}'),
      leading: onBackToCabinets == null
          ? null
          : BackButton(onPressed: onBackToCabinets),
      actions: [
        IconButton(
          key: const Key('passenger-entry-advance-booking'),
          tooltip: pdTr(context, 'Предварительный заказ',
              'Išankstinis užsakymas', 'Advance booking'),
          icon: const Icon(Icons.event_available_outlined),
          onPressed: () => _startAdvanceBooking(context),
        ),
        PopupMenuButton<ExtraServiceType>(
          key: const Key('passenger-entry-services'),
          tooltip: pdTr(context, 'Наши услуги', 'Mūsų paslaugos', 'Our services'),
          icon: const Icon(Icons.miscellaneous_services_outlined),
          onSelected: (type) => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => PdPassengerLanguageScope(
                child: PassengerExtraServices(type: type, tripStore: tripStore),
              ),
            ),
          ),
          itemBuilder: (_) => [
            PopupMenuItem(
              key: const Key('passenger-services-delivery'),
              value: ExtraServiceType.delivery,
              child: Text(pdTr(context, 'Доставка товаров · 20 €',
                'Prekių pristatymas · 20 €', 'Goods delivery · €20')),
            ),
            PopupMenuItem(
              value: ExtraServiceType.jumpstart,
              child: Text(pdTr(context, 'Запуск автомобиля · 20 €',
                'Automobilio užvedimas · 20 €', 'Car jump-start · €20')),
            ),
          ],
        ),
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
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
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
          ])),
      ),
    ))),
    ]),
  );
}
