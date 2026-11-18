import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'demo_trip_store.dart';

/// Offline dispatcher console: one session-local pilot and one synthetic order.
/// No fabricated pilot locations, real drivers, server access or payments.
class DemoDispatcherCabinet extends StatefulWidget {
  const DemoDispatcherCabinet({
    super.key, required this.tripStore, this.enableMapTiles = true,
  });

  final DemoTripStore tripStore;
  final bool enableMapTiles;

  @override
  State<DemoDispatcherCabinet> createState() => _DemoDispatcherCabinetState();
}

class _DemoDispatcherCabinetState extends State<DemoDispatcherCabinet> {
  int _tab = 0;
  static const gold = Color(0xFFDDC184);
  static const tabs = ['Заказы', 'Карта', 'Пилоты', 'Пассажиры'];

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE · Диспетчер · DEMO')),
    body: Column(children: [
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          for (var index = 0; index < tabs.length; index++)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: ChoiceChip(
                key: Key('dispatcher-tab-$index'),
                label: Text(tabs[index]),
                selected: _tab == index,
                onSelected: (_) => setState(() => _tab = index),
              ),
            ),
        ]),
      ),
      Expanded(child: AnimatedBuilder(
        animation: widget.tripStore,
        builder: (context, _) => switch (_tab) {
          0 => _orders(),
          1 => _fleetMap(),
          2 => _pilots(),
          _ => _passengers(),
        },
      )),
    ]),
  );

  Widget _orders() {
    final trip = widget.tripStore.trip;
    final status = widget.tripStore.status;
    return ListView(
      key: const Key('dispatcher-cabinet'),
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Контроль заказов · DEMO', style: TextStyle(
          fontWeight: FontWeight.bold, color: gold, fontSize: 18)),
        const Text('Назначение только вручную. Локальные тестовые данные.'),
        if (trip == null) const Card(child: Padding(
          padding: EdgeInsets.all(16),
          child: Text('Новых тестовых заявок нет',
            key: Key('dispatcher-empty')),
        )),
        if (trip != null) Card(
          key: const Key('dispatcher-order-card'),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(widget.tripStore.statusLabel,
                  key: const Key('dispatcher-order-status'),
                  style: const TextStyle(color: gold,
                    fontWeight: FontWeight.bold)),
                Text('Подача: ${trip.from}',
                  key: const Key('dispatcher-pickup')),
                Text('Назначение: ${trip.to}'),
                Text('Оплата: ${trip.paymentMethod}'),
                Text('Дата: ${trip.departure.day}.${trip.departure.month}.${trip.departure.year}'),
                if (trip.services.isNotEmpty)
                  Text('Услуги: ${trip.services.join(', ')}'),
                const SizedBox(height: 12),
                if (status == DemoTripStatus.requested)
                  FilledButton.icon(
                    key: const Key('dispatcher-assign-pilot'),
                    onPressed: widget.tripStore.assignPilot,
                    icon: const Icon(Icons.assignment_ind_outlined),
                    label: const Text('Назначить тестового пилота'),
                  ),
                if (status == DemoTripStatus.assigned &&
                    !widget.tripStore.pilotAccepted)
                  const Text('Назначено пилоту · ожидает принятия'),
                if (status == DemoTripStatus.assigned &&
                    widget.tripStore.pilotAccepted)
                  const Text('Пилот принял заказ'),
                if (status == DemoTripStatus.finished) ...[
                  const Text('Заказ завершён'),
                  Text(widget.tripStore.tripRating == null
                    ? 'Оценка пассажира ещё не получена'
                    : 'Поездка: ${widget.tripStore.tripRating}/5 · '
                      'Сервис: ${widget.tripStore.serviceRating}/5'),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _fleetMap() {
    final store = widget.tripStore;
    final latitude = store.pilotLatitude;
    final longitude = store.pilotLongitude;
    final hasFix = store.pilotOnline &&
        latitude != null && longitude != null;
    final point = hasFix ? LatLng(latitude, longitude) : null;
    return Column(key: const Key('dispatcher-map-tab'), children: [
      const Padding(
        padding: EdgeInsets.all(12),
        child: Text('Карта активных пилотов · DEMO',
          style: TextStyle(color: gold, fontWeight: FontWeight.bold)),
      ),
      Expanded(child: widget.enableMapTiles
        ? FlutterMap(
            key: const Key('dispatcher-live-map'),
            options: MapOptions(
              initialCenter: point ?? const LatLng(54.6872, 25.2797),
              initialZoom: 12,
            ),
            children: [
              TileLayer(
                urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'lt.privatedrive.privateDrive',
              ),
              if (point != null) MarkerLayer(markers: [
                Marker(
                  point: point, width: 48, height: 48,
                  child: const Icon(Icons.directions_car,
                    key: Key('dispatcher-pilot-marker'),
                    color: gold, size: 40),
                ),
              ]),
              const RichAttributionWidget(attributions: [
                TextSourceAttribution('© OpenStreetMap contributors'),
              ]),
            ],
          )
        : const ColoredBox(
            key: Key('dispatcher-live-map'),
            color: Color(0xFF18212C),
            child: Center(child: Text('Карта · без сетевых тайлов')),
          ),
      ),
      Padding(
        padding: const EdgeInsets.all(12),
        child: Text(
          hasFix
            ? '1 пилот с GPS · только локальная сессия'
            : 'Подтверждённых GPS-точек нет. Для нескольких пилотов '
              'нужна защищённая серверная синхронизация.',
          key: const Key('dispatcher-fleet-status'),
          textAlign: TextAlign.center,
        ),
      ),
    ]);
  }

  Widget _pilots() {
    final store = widget.tripStore;
    return ListView(key: const Key('dispatcher-pilots-tab'),
      padding: const EdgeInsets.all(16),
      children: [
        const Text('ПИЛОТЫ · DEMO', style: TextStyle(color: gold,
          fontWeight: FontWeight.bold, fontSize: 19)),
        Card(child: ListTile(
          leading: const Icon(Icons.directions_car),
          title: const Text('Тестовый пилот · текущая сессия'),
          subtitle: Text(
            '${store.pilotOnline ? 'На линии' : 'Не на линии'} · '
            '${store.pilotLatitude == null ? 'GPS нет' : 'GPS доступен'} · '
            '${store.statusLabel}',
          ),
        )),
        const Text('Реестр других пилотов и документы появятся только '
          'после подключения защищённого API и проверки прав диспетчера.'),
      ],
    );
  }

  Widget _passengers() {
    final trip = widget.tripStore.trip;
    return ListView(key: const Key('dispatcher-passengers-tab'),
      padding: const EdgeInsets.all(16),
      children: [
        const Text('ПАССАЖИРЫ · DEMO', style: TextStyle(color: gold,
          fontWeight: FontWeight.bold, fontSize: 19)),
        if (trip == null)
          const Text('В текущей сессии пассажирские заявки отсутствуют'),
        if (trip != null)
          Card(child: ListTile(
            leading: const Icon(Icons.person),
            title: const Text('Тестовый пассажир · без персональных данных'),
            subtitle: Text('${trip.from} → ${trip.to} · '
              '${widget.tripStore.statusLabel}'),
          )),
        const Text('Телефоны, профили и реальные пассажиры не загружаются '
          'без серверной авторизации диспетчера.'),
      ],
    );
  }
}
