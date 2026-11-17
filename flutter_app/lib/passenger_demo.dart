import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart' show LatLng;

/// Passenger preview: all trip, date, service and payment state stays in memory.
/// Map tiles are the only possible network activity; there is no orders API,
/// geocoding, payment SDK, charge or persistent booking in this screen.
class PassengerDemo extends StatefulWidget {
  const PassengerDemo({super.key, this.enableMapTiles = true, this.tripStore});

  final bool enableMapTiles;
  final DemoTripStore? tripStore;

  @override
  State<PassengerDemo> createState() => _PassengerDemoState();
}

class _PassengerDemoState extends State<PassengerDemo> {
  final _from = TextEditingController();
  final _to = TextEditingController();
  DateTime? _date;
  TimeOfDay? _time;
  String _route = '';
  String _payment = 'Карта';
  bool _meetSign = false;
  bool _pets = false;
  bool _soberDriver = false;
  bool _music = false;


  @override
  void initState() {
    super.initState();
    widget.tripStore?.addListener(_onTripChanged);
  }

  void _onTripChanged() {
    if (mounted) setState(() {});
  }

  void _createLocalTrip() {
    final store = widget.tripStore;
    if (store == null) return;
    final date = _date ?? DateUtils.dateOnly(DateTime.now());
    final time = _time ?? TimeOfDay.now();
    final departure = DateTime(date.year, date.month, date.day,
        time.hour, time.minute);
    store.create(
      from: _from.text,
      to: _to.text,
      paymentMethod: _payment,
      departure: departure,
      services: [
        if (_meetSign) 'Встреча с табличкой',
        if (_pets) 'Животные',
        if (_soberDriver) 'Трезвый водитель',
        if (_music) 'Музыка в дорогу',
      ],
    );
  }

  bool get _canCreateLocalTrip {
    final store = widget.tripStore;
    final a = _from.text.trim();
    final b = _to.text.trim();
    return store != null && !store.isActive && a.isNotEmpty &&
        b.isNotEmpty && a.toLowerCase() != b.toLowerCase();
  }

  static const _places = <String, LatLng>{
    'Вильнюс': LatLng(54.6872, 25.2797),
    'Каунас': LatLng(54.8985, 23.9036),
    'Клайпеда': LatLng(55.7033, 21.1443),
    'Паланга': LatLng(55.9175, 21.0686),
    'Варшава': LatLng(52.2297, 21.0122),
    'Аэропорт Вильнюса': LatLng(54.6341, 25.2858),
  };

  void _chooseRoute(String route, String from, String to) {
    setState(() {
      _route = route;
      _from.text = from;
      _to.text = to;
    });
  }

  Future<void> _pickDate() async {
    final today = DateUtils.dateOnly(DateTime.now());
    final selected = await showDatePicker(
      context: context,
      initialDate: _date ?? today,
      firstDate: today,
      lastDate: today.add(const Duration(days: 365)),
    );
    if (selected != null && mounted) setState(() => _date = selected);
  }

  Future<void> _pickTime() async {
    final selected = await showTimePicker(
      context: context,
      initialTime: _time ?? TimeOfDay.now(),
    );
    if (selected != null && mounted) setState(() => _time = selected);
  }

  @override
  void dispose() {
    widget.tripStore?.removeListener(_onTripChanged);
    _from.dispose();
    _to.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    final start = _places[_from.text.trim()];
    final finish = _places[_to.text.trim()];
    final mapMarkers = <Marker>[
      if (start != null)
        Marker(
          point: start,
          width: 48,
          height: 48,
          child: const Icon(Icons.trip_origin, color: gold, size: 32),
        ),
      if (finish != null)
        Marker(
          point: finish,
          width: 48,
          height: 48,
          child: const Icon(Icons.location_on, color: Colors.redAccent, size: 34),
        ),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE · Пассажир')),
      body: SafeArea(
        child: ListView(
          key: const Key('passenger-form'),
          padding: const EdgeInsets.all(16),
          children: [
            const Text('Тестовый заказ поездки', style: TextStyle(fontSize: 22)),
            const SizedBox(height: 6),
            const Text('Демонстрация. Не отправляет заказы и не списывает деньги.'),
            const SizedBox(height: 12),
            SizedBox(
              height: 195,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: widget.enableMapTiles
                    ? FlutterMap(
                        key: const Key('passenger-map'),
                        options: const MapOptions(
                          initialCenter: LatLng(54.6872, 25.2797),
                          initialZoom: 10,
                        ),
                        children: [
                          TileLayer(
                            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                            userAgentPackageName: 'lt.privatedrive.privateDrive',
                          ),
                          MarkerLayer(markers: mapMarkers),
                          const RichAttributionWidget(
                            attributions: [
                              TextSourceAttribution('© OpenStreetMap contributors'),
                            ],
                          ),
                        ],
                      )
                    : const ColoredBox(
                        key: Key('passenger-map'),
                        color: Color(0xFF27332F),
                        child: Center(child: Text('Карта · офлайн-тест')),
                      ),
              ),
            ),
            const SizedBox(height: 12),
            const Text('Популярные направления'),
            Wrap(
              spacing: 6,
              children: [
                ActionChip(
                  key: const Key('route-kaunas'),
                  label: const Text('Вильнюс — Каунас'),
                  onPressed: () => _chooseRoute('Вильнюс — Каунас', 'Вильнюс', 'Каунас'),
                ),
                ActionChip(
                  key: const Key('route-airport'),
                  label: const Text('Аэропорт'),
                  onPressed: () => _chooseRoute('Аэропорт', 'Вильнюс', 'Аэропорт Вильнюса'),
                ),
                ActionChip(
                  key: const Key('route-warsaw'),
                  label: const Text('Вильнюс — Варшава'),
                  onPressed: () => _chooseRoute('Вильнюс — Варшава', 'Вильнюс', 'Варшава'),
                ),
                ActionChip(
                  key: const Key('route-palanga'),
                  label: const Text('Вильнюс — Паланга'),
                  onPressed: () => _chooseRoute('Вильнюс — Паланга', 'Вильнюс', 'Паланга'),
                ),
              ],
            ),
            TextField(
              key: const Key('passenger-from'),
              controller: _from,
              onChanged: (_) => setState(() => _route = ''),
              decoration: const InputDecoration(
                labelText: 'Откуда', prefixIcon: Icon(Icons.trip_origin),
              ),
            ),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('passenger-to'),
                    controller: _to,
                    onChanged: (_) => setState(() => _route = ''),
                    decoration: const InputDecoration(
                      labelText: 'Куда', prefixIcon: Icon(Icons.location_on_outlined),
                    ),
                  ),
                ),
                IconButton(
                  key: const Key('passenger-swap'),
                  tooltip: 'Поменять А и Б',
                  onPressed: () => setState(() {
                    final previous = _from.text;
                    _from.text = _to.text;
                    _to.text = previous;
                    _route = '';
                  }),
                  icon: const Icon(Icons.swap_vert),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    key: const Key('passenger-date'),
                    onPressed: _pickDate,
                    icon: const Icon(Icons.calendar_today),
                    label: Text(_date == null
                        ? 'Дата'
                        : '${_date!.day.toString().padLeft(2, '0')}.${_date!.month.toString().padLeft(2, '0')}.${_date!.year}'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    key: const Key('passenger-time'),
                    onPressed: _pickTime,
                    icon: const Icon(Icons.schedule),
                    label: Text(_time == null ? 'Время' : _time!.format(context)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            const Text('Дополнительные услуги', style: TextStyle(fontWeight: FontWeight.bold)),
            CheckboxListTile(
              key: const Key('service-meet-sign'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: const Text('Встреча с табличкой · +15 €'),
              value: _meetSign,
              onChanged: (v) => setState(() => _meetSign = v ?? false),
            ),
            CheckboxListTile(
              key: const Key('service-pets'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: const Text('Поездка с животными · цена по запросу'),
              value: _pets,
              onChanged: (v) => setState(() => _pets = v ?? false),
            ),
            CheckboxListTile(
              key: const Key('service-sober'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: const Text('Трезвый водитель · цена по запросу'),
              value: _soberDriver,
              onChanged: (v) => setState(() => _soberDriver = v ?? false),
            ),
            CheckboxListTile(
              key: const Key('service-music'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: const Text('Музыка в дорогу · бесплатно'),
              value: _music,
              onChanged: (v) => setState(() => _music = v ?? false),
            ),
            const SizedBox(height: 12),
            const Text('Способ оплаты · только выбор', style: TextStyle(fontWeight: FontWeight.bold)),
            Wrap(
              spacing: 8,
              children: [
                for (final method in ['Карта', 'PayPal', 'Банковский перевод', 'Криптовалюта'])
                  ChoiceChip(
                    key: Key('payment-$method'),
                    label: Text(method),
                    selected: _payment == method,
                    onSelected: (_) => setState(() => _payment = method),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              'Выбрано: ${_route.isNotEmpty ? _route : 'свой маршрут'} · $_payment',
              key: const Key('passenger-summary'),
            ),
            const SizedBox(height: 12),
            if (widget.tripStore != null)
              Text(widget.tripStore!.statusLabel,
                  key: const Key('passenger-trip-status')),
            FilledButton(
              key: const Key('passenger-book-disabled'),
              onPressed: _canCreateLocalTrip ? _createLocalTrip : null,
              child: Text(widget.tripStore == null
                  ? 'Заказать поездку — недоступно в демоверсии'
                  : 'Создать тестовую заявку · без сервера'),
            ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
  }
}
