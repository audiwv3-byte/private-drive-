import 'package:flutter/material.dart';
import 'native_orders_api.dart';
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
    this.ordersApi,
  });

  final NativeOrdersApi? ordersApi;
  final bool enableMapTiles;
  final DemoTripStore tripStore;
  final VoidCallback? onSignOut;
  final VoidCallback? onBackToCabinets;

  void _openExtra(BuildContext context, ExtraServiceType service) {
    if (ordersApi != null) {
      Navigator.push(context, MaterialPageRoute<void>(
        builder: (_) => PdPassengerLanguageScope(
          child: PassengerDemo(
            enableMapTiles: enableMapTiles,
            tripStore: tripStore,
            initialExtraService: service == ExtraServiceType.jumpstart
                ? 'jumpstart' : 'delivery',
            ordersApi: ordersApi,
          ),
        ),
      ));
      return;
    }
    Navigator.push(context, MaterialPageRoute<void>(
      builder: (_) => PdPassengerLanguageScope(
        child: PassengerExtraServices(
          type: service, tripStore: tripStore),
      ),
    ));
  }

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
          ordersApi: ordersApi,
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
        const PdLanguageMenu(),
        if (ordersApi != null) IconButton(icon: const Icon(Icons.history), tooltip: 'Мои заказы', onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => NativeOrdersHistory(api: ordersApi!)))),
        if (onSignOut != null)
          IconButton(
            key: const Key('passenger-sign-out'),
            tooltip: 'Выйти',
            icon: const Icon(Icons.logout),
            onPressed: onSignOut,
          ),
      ]),
    body: Stack(fit: StackFit.expand, children: [
      const VilniusEveningBackdrop(),
      SafeArea(child: Center(child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 460),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: ListView(shrinkWrap: true, children: [
            const Center(
              child: PrivateDriveBrandLogo(
                size: 80, transparentBackground: true)),
            const SizedBox(height: 12),
            SizedBox(width: double.infinity, child: FilledButton.icon(
              key: const Key('passenger-entry-advance-booking'),
              icon: const Icon(Icons.event_available_outlined),
              label: Text(pdTr(context, 'Предварительный заказ',
                'Išankstinis užsakymas', 'Advance booking')),
              onPressed: () => _startAdvanceBooking(context),
            )),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: SizedBox(
                key: const Key('passenger-entry-vilnius-panorama'),
                height: 86,
                child: Image.asset(
                  'assets/brand/vilnius_cathedral_user_photo.webp',
                  fit: BoxFit.cover,
                  alignment: const Alignment(-0.48, 0),
                ),
              ),
            ),
            const SizedBox(height: 8),
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
            const Divider(),
            const SizedBox(height: 8),
            Text('Дополнительные услуги',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 19,
                fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            Card(child: ListTile(
              key: const Key('passenger-entry-jumpstart'),
              leading: const Icon(Icons.battery_charging_full, size: 34),
              title: Text(ordersApi == null ? 'Запуск автомобиля · 20 €' : 'Запуск автомобиля · цена по запросу'),
              subtitle: const Text(
                'Помощь с разряженным аккумулятором'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _openExtra(context, ExtraServiceType.jumpstart),
            )),
            const SizedBox(height: 12),
            Card(child: ListTile(
              key: const Key('passenger-entry-delivery'),
              leading: const Icon(Icons.shopping_bag_outlined, size: 34),
              title: Text(ordersApi == null ? 'Доставка товаров · 20 €' : 'Доставка товаров · цена по запросу'),
              subtitle: const Text('Заберём покупки из магазина и доставим'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _openExtra(context, ExtraServiceType.delivery),
            )),
            const SizedBox(height: 20),
            Text(
              ordersApi == null
                  ? pdLabel(context, 'Демонстрационный режим: заявки остаются на устройстве.')
                  : 'Заказы передаются через защищённый сервер. Оплата отключена.',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 12)),
          ]),
      ),
    ))),
    ]),
  );
}
