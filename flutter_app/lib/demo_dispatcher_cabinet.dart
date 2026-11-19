import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'demo_trip_store.dart';
import 'app_language.dart';

/// Offline dispatcher console: one session-local pilot and one synthetic order.
/// No fabricated pilot locations, real drivers, server access or payments.
class DemoDispatcherCabinet extends StatefulWidget {
  const DemoDispatcherCabinet({
    super.key, required this.tripStore, this.enableMapTiles = true,
    this.initialTab = 1,
  });

  final DemoTripStore tripStore;
  final bool enableMapTiles;
  /// Open on the fleet map; callers can deep-link directly to another section.
  final int initialTab;

  @override
  State<DemoDispatcherCabinet> createState() => _DemoDispatcherCabinetState();
}

class _DemoDispatcherCabinetState extends State<DemoDispatcherCabinet> {
  late int _tab;

  @override
  void initState() {
    super.initState();
    _tab = widget.initialTab.clamp(0, 3);
  }
  static const gold = Color(0xFFDDC184);
  static const tabs = ['Заказы', 'Карта', 'Пилоты', 'Пассажиры'];

  void _selectSection(int index) {
    Navigator.of(context).pop();
    setState(() => _tab = index);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    drawer: Drawer(
      key: const Key('dispatcher-navigation-drawer'),
      child: SafeArea(child: ListView(children: [
        const DrawerHeader(child: Center(child: Text('PRIVATE DRIVE · Диспетчер',
          style: TextStyle(fontSize: 20, color: gold)))),
        for (var index = 0; index < tabs.length; index++)
          ListTile(
            key: Key('dispatcher-menu-$index'),
            leading: Icon([Icons.receipt_long_outlined, Icons.map_outlined,
              Icons.directions_car_outlined, Icons.people_outline][index]),
            title: Text(pdLabel(context, tabs[index])),
            selected: _tab == index,
            onTap: () => _selectSection(index),
          ),
        const Divider(),
        const ListTile(leading: Icon(Icons.credit_card_outlined),
          title: Text('Платежи · доступно после подключения API'), enabled: false),
        const ListTile(leading: Icon(Icons.bar_chart_outlined),
          title: Text('Отчёты · доступно после подключения API'), enabled: false),
      ])),
    ),
    appBar: AppBar(
      title: Text('PRIVATE DRIVE · ${pdLabel(context, 'Диспетчер')} · DEMO'),
      actions: [IconButton(
        tooltip: 'Карта пилотов',
        key: const Key('dispatcher-map-home'),
        icon: const Icon(Icons.map_outlined),
        onPressed: () => setState(() => _tab = 1),
      )],
    ),
    body: Column(children: [
      if (widget.initialTab == 0)
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (var index = 0; index < tabs.length; index++)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3),
                child: ChoiceChip(
                  key: Key('dispatcher-tab-$index'),
                  label: Text(pdLabel(context, tabs[index])),
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
        Text(pdLabel(context, 'Контроль заказов · DEMO'), style: TextStyle(
          fontWeight: FontWeight.bold, color: gold, fontSize: 18)),
        Text(pdLabel(context, 'Назначение только вручную. Локальные тестовые данные.')),
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
                Text('${pdLabel(context, 'Подача')}: ${trip.from}',
                  key: const Key('dispatcher-pickup')),
                Text('${pdLabel(context, 'Назначение')}: ${trip.to}'),
                Text('${pdLabel(context, 'Оплата')}: ${trip.paymentMethod}'),
                Text('Дата: ${trip.departure.day}.${trip.departure.month}.${trip.departure.year}'),
                if (trip.services.isNotEmpty)
                  Text('${pdLabel(context, 'Услуги')}: ${trip.services.join(', ')}'),
                const SizedBox(height: 12),
                if (status == DemoTripStatus.requested)
                  FilledButton.icon(
                    key: const Key('dispatcher-assign-pilot'),
                    onPressed: widget.tripStore.assignPilot,
                    icon: const Icon(Icons.assignment_ind_outlined),
                    label: Text(pdLabel(context, 'Назначить тестового пилота')),
                  ),
                if (status == DemoTripStatus.assigned &&
                    !widget.tripStore.pilotAccepted)
                  Text(pdLabel(context, 'Назначено пилоту · ожидает принятия')),
                if (status == DemoTripStatus.assigned &&
                    widget.tripStore.pilotAccepted)
                  Text(pdLabel(context, 'Пилот принял заказ')),
                if (status == DemoTripStatus.finished) ...[
                  Text(pdLabel(context, 'Заказ завершён')),
                  Text(widget.tripStore.tripRating == null
                    ? 'Оценка пассажира ещё не получена'
                    : 'Поездка: ${widget.tripStore.tripRating}/5 · '
                      'Сервис: ${widget.tripStore.serviceRating}/5'),
                ],
              ],
            ),
          ),
        ),
        if (trip != null)
          _chatPanel(
            title: 'Переписка по текущему заказу',
            route: '${trip.from} → ${trip.to}',
            pilotMessages: widget.tripStore.pilotChatMessages,
            passengerMessages: widget.tripStore.passengerChatMessages,
            key: const Key('dispatcher-current-chat'),
          ),
        for (final (index, entry) in widget.tripStore.archivedChats.reversed.indexed)
          _chatPanel(
            title: 'История переписки',
            route: '${entry.from} → ${entry.to}',
            pilotMessages: entry.pilotMessages,
            passengerMessages: entry.passengerMessages,
            key: ValueKey('dispatcher-archived-chat-$index'),
          ),
        const SizedBox(height: 8),
        const Text('Чаты DEMO сохраняются только на этом устройстве. '
          'Для безопасной синхронизации между устройствами требуется сервер '
          'и проверка прав диспетчера.'),
      ],
    );
  }

  Widget _chatPanel({
    required Key key,
    required String title,
    required String route,
    required List<String> pilotMessages,
    required List<String> passengerMessages,
  }) => Card(
    key: key,
    child: ExpansionTile(
      title: Text(title),
      subtitle: Text(route),
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      children: [
        if (pilotMessages.isEmpty && passengerMessages.isEmpty)
          const Text('Сообщений по заказу пока нет'),
        if (pilotMessages.isNotEmpty) ...[
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('Пилот', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          for (final message in pilotMessages)
            ListTile(
              dense: true,
              // No constant key: multiple messages share the same parent.
              leading: const Icon(Icons.directions_car_outlined),
              title: Text(message),
            ),
        ],
        if (passengerMessages.isNotEmpty) ...[
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('Пассажир', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          for (final message in passengerMessages)
            ListTile(
              dense: true,
              // Each message is read-only; ordering is defined by its list.
              leading: const Icon(Icons.person_outline),
              title: Text(message),
            ),
        ],
        const Text('Только просмотр. Сообщения пилота и пассажира '
          'не редактируются диспетчером.'),
      ],
    ),
  );

  Widget _fleetMap() {
    final store = widget.tripStore;
    final latitude = store.pilotLatitude;
    final longitude = store.pilotLongitude;
    final hasFix = store.pilotOnline &&
        latitude != null && longitude != null;
    final point = hasFix ? LatLng(latitude, longitude) : null;
    return Stack(key: const Key('dispatcher-map-tab'), children: [
      Positioned.fill(child: widget.enableMapTiles
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
                  point: point, width: 64, height: 64,
                  child: const CustomPaint(
                    key: Key('dispatcher-pilot-marker'),
                    painter: _GoldPilotArrowPainter(),
                  ),
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
      Positioned(
        left: 12, right: 12, bottom: 12,
        child: Material(color: const Color(0xDB151D2A),
          borderRadius: BorderRadius.circular(10), child: Padding(
        padding: const EdgeInsets.all(12),
        child: Text(
          hasFix
            ? '1 пилот с GPS · только локальная сессия'
            : 'Подтверждённых GPS-точек нет. Для нескольких пилотов '
              'нужна защищённая серверная синхронизация.',
          key: const Key('dispatcher-fleet-status'),
          textAlign: TextAlign.center,
        ),
        ))),
    ]);
  }

  Widget _pilots() {
    final store = widget.tripStore;
    return ListView(key: const Key('dispatcher-pilots-tab'),
      padding: const EdgeInsets.all(16),
      children: [
        Text(pdLabel(context, 'ПИЛОТЫ · DEMO'), style: TextStyle(color: gold,
          fontWeight: FontWeight.bold, fontSize: 19)),
        Card(child: ListTile(
          leading: const Icon(Icons.directions_car),
          title: Text(pdLabel(context, 'Тестовый пилот · текущая сессия')),
          subtitle: Text(
            '${pdLabel(context, store.pilotOnline ? 'На линии' : 'Не на линии')} · '
            '${pdLabel(context, store.pilotLatitude == null ? 'GPS нет' : 'GPS доступен')} · '
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
        Text(pdLabel(context, 'ПАССАЖИРЫ · DEMO'), style: TextStyle(color: gold,
          fontWeight: FontWeight.bold, fontSize: 19)),
        if (trip == null)
          Text(pdLabel(context, 'В текущей сессии пассажирские заявки отсутствуют')),
        if (trip != null)
          Card(child: ListTile(
            leading: const Icon(Icons.person),
            title: Text(pdLabel(context, 'Тестовый пассажир · без персональных данных')),
            subtitle: Text('${trip.from} → ${trip.to} · '
              '${widget.tripStore.statusLabel}'),
          )),
        const Text('Телефоны, профили и реальные пассажиры не загружаются '
          'без серверной авторизации диспетчера.'),
      ],
    );
  }
}


/// High-contrast approved marker B: gold navigation arrow with a thick
/// near-black outline, visible on both light and dark map tiles.
/// The dispatcher demo has no trustworthy heading data, so the arrow
/// deliberately points north rather than inventing a driving direction.
class _GoldPilotArrowPainter extends CustomPainter {
  const _GoldPilotArrowPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final halo = Paint()
      ..color = const Color(0xD9000000)
      ..style = PaintingStyle.fill;
    canvas.drawCircle(center, size.shortestSide * 0.47, halo);
    canvas.drawCircle(center, size.shortestSide * 0.415,
        Paint()..color = const Color(0xFFFFDF87));
    canvas.drawCircle(center, size.shortestSide * 0.36,
        Paint()..color = const Color(0xFF15191E));

    final arrow = ui.Path()
      ..moveTo(size.width * 0.50, size.height * 0.10)
      ..lineTo(size.width * 0.81, size.height * 0.81)
      ..lineTo(size.width * 0.50, size.height * 0.64)
      ..lineTo(size.width * 0.19, size.height * 0.81)
      ..close();
    canvas.drawPath(arrow, Paint()
      ..color = const Color(0xFF05080C)
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.shortestSide * 0.105
      ..strokeJoin = StrokeJoin.round);
    canvas.drawPath(arrow, Paint()..color = const Color(0xFFF2BC35));
    canvas.drawLine(
      Offset(size.width * 0.50, size.height * 0.22),
      Offset(size.width * 0.50, size.height * 0.57),
      Paint()
        ..color = const Color(0xFFFFEDAD)
        ..strokeWidth = size.shortestSide * 0.035
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(covariant _GoldPilotArrowPainter oldDelegate) => false;
}
