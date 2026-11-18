import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'demo_rating_panel.dart';
import 'company_info.dart';
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
  List<LatLng> _roadPoints = const [];
  bool _routeLoading = false;
  String _routeInfo = '';
  int _routeRequest = 0;


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

  /// Only an agreed fixed price is shown. Other routes remain quote-only.
  int? get _fixedPrice {
    final a = _from.text.trim().toLowerCase();
    final b = _to.text.trim().toLowerCase();
    if ((a == 'вильнюс' && b == 'каунас') ||
        (a == 'каунас' && b == 'вильнюс')) return 130;
    return null;
  }

  int? get _pricePreview {
    final base = _fixedPrice;
    if (base == null || _pets || _soberDriver) return null;
    return base + (_meetSign ? 15 : 0);
  }

  /// Public routing service is used only for a preview of preset city routes.
  /// Failure is displayed explicitly; never pretend a straight line is a road.
  Future<void> _updateRoadPreview() async {
    final request = ++_routeRequest;
    final start = _places[_from.text.trim()];
    final finish = _places[_to.text.trim()];
    if (start == null || finish == null || !widget.enableMapTiles) {
      if (mounted) setState(() {
        _roadPoints = const [];
        _routeLoading = false;
        _routeInfo = start == null || finish == null
            ? 'Для своего адреса требуется подключение поиска адресов.'
            : '';
      });
      return;
    }
    setState(() {
      _routeLoading = true;
      _roadPoints = const [];
      _routeInfo = 'Построение дорожного маршрута · демо…';
    });
    HttpClient? client;
    try {
      client = HttpClient()..connectionTimeout = const Duration(seconds: 6);
      final uri = Uri.https('router.project-osrm.org',
          '/route/v1/driving/${start.longitude},${start.latitude};${finish.longitude},${finish.latitude}',
          {'overview': 'full', 'geometries': 'geojson'});
      final response = await (await client.getUrl(uri).timeout(
        const Duration(seconds: 8))).close().timeout(
        const Duration(seconds: 8));
      if (response.statusCode != 200) throw const HttpException('Routing unavailable');
      final decoded = jsonDecode(await utf8.decoder.bind(response).join()
          .timeout(const Duration(seconds: 8))) as Map<String, dynamic>;
      final routes = decoded['routes'] as List<dynamic>?;
      if (routes == null || routes.isEmpty) throw const FormatException('No road route');
      final route = routes.first as Map<String, dynamic>;
      final coordinates = (route['geometry'] as Map<String, dynamic>)['coordinates']
          as List<dynamic>;
      final points = coordinates.map((raw) {
        final p = raw as List<dynamic>;
        return LatLng((p[1] as num).toDouble(), (p[0] as num).toDouble());
      }).toList(growable: false);
      if (points.length < 2) throw const FormatException('Empty road route');
      if (!mounted || request != _routeRequest) return;
      setState(() {
        _roadPoints = points;
        _routeLoading = false;
        final km = ((route['distance'] as num).toDouble() / 1000).round();
        _routeInfo = 'Дорожный маршрут · около $km км · демо';
      });
    } catch (_) {
      if (!mounted || request != _routeRequest) return;
      setState(() {
        _roadPoints = const [];
        _routeLoading = false;
        _routeInfo = 'Дорожный маршрут временно недоступен.';
      });
    } finally {
      client?.close(force: true);
    }
  }

  void _chooseRoute(String route, String from, String to) {
    setState(() {
      _route = route;
      _from.text = from;
      _to.text = to;
    });
    _updateRoadPreview();
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
    _routeRequest++;
    _from.dispose();
    _to.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    final start = _places[_from.text.trim()];
    final finish = _places[_to.text.trim()];
    final price = _pricePreview;
    final startMap = start != null && finish != null
        ? LatLng((start.latitude + finish.latitude) / 2,
            (start.longitude + finish.longitude) / 2)
        : start ?? const LatLng(54.6872, 25.2797);
    final mapZoom = start != null && finish != null
        ? (start.longitude - finish.longitude).abs() > 2 ? 6.3 : 8.2
        : 10.0;
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
      appBar: AppBar(
        title: const Text('PRIVATE DRIVE · Пассажир'),
        actions: [
          IconButton(
            key: const Key('passenger-company-info'),
            tooltip: 'Контакты и документы',
            onPressed: () => Navigator.push(context, MaterialPageRoute(
              builder: (_) => const CompanyInfoPage())),
            icon: const Icon(Icons.info_outline),
          ),
        ],
      ),
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
                    ? KeyedSubtree(
                        key: ValueKey('passenger-route-map-${_from.text}-${_to.text}'),
                        child: FlutterMap(
                        key: const Key('passenger-map'),
                        options: MapOptions(
                          initialCenter: startMap,
                          initialZoom: mapZoom,
                        ),
                        children: [
                          TileLayer(
                            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                            userAgentPackageName: 'lt.privatedrive.privateDrive',
                          ),
                          if (_roadPoints.isNotEmpty)
                            PolylineLayer(
                              key: const Key('passenger-road-route'),
                              polylines: [
                                Polyline(
                                  points: _roadPoints,
                                  color: gold,
                                  strokeWidth: 5,
                                ),
                              ],
                            ),
                          MarkerLayer(markers: mapMarkers),
                          const RichAttributionWidget(
                            attributions: [
                              TextSourceAttribution('© OpenStreetMap contributors'),
                            ],
                          ),
                        ],
                        ),
                      )
                    : const ColoredBox(
                        key: Key('passenger-map'),
                        color: Color(0xFF27332F),
                        child: Center(child: Text('Карта · офлайн-тест')),
                      ),
              ),
            ),
            if (_routeInfo.isNotEmpty)
              Text(_routeInfo, key: const Key('passenger-route-info'),
                  style: const TextStyle(fontSize: 12)),
            if (_routeLoading)
              const LinearProgressIndicator(key: Key('passenger-route-loading')),
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
              onChanged: (_) { setState(() => _route = ''); _updateRoadPreview(); },
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
                  onPressed: () {
                    setState(() {
                      final previous = _from.text;
                      _from.text = _to.text;
                      _to.text = previous;
                      _route = '';
                    });
                    _updateRoadPreview();
                  },
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
              price != null ? 'Предварительная стоимость: $price €'
                  : _fixedPrice != null
                    ? 'Стоимость по запросу: дополнительные услуги требуют расчёта'
                    : 'Стоимость по запросу · фиксированная цена не установлена',
              key: const Key('passenger-price-preview'),
              style: const TextStyle(
                color: gold, fontWeight: FontWeight.bold, fontSize: 16,
              ),
            ),
            const Text('Демо-расчёт. Итоговая цена подтверждается до оплаты.',
              style: TextStyle(fontSize: 12)),
            const SizedBox(height: 12),
            Text(
              'Выбрано: ${_route.isNotEmpty ? _route : 'свой маршрут'} · $_payment',
              key: const Key('passenger-summary'),
            ),
            const SizedBox(height: 12),
            if (widget.tripStore != null) ...[
              Text(widget.tripStore!.statusLabel,
                  key: const Key('passenger-trip-status')),
              DemoRatingPanel(tripStore: widget.tripStore!),
            ],
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
