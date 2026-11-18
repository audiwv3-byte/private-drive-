import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'demo_rating_panel.dart';
import 'company_info.dart';
import 'passenger_orders_demo.dart';
import 'dart:math' as math;
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
  final _tripWishes = TextEditingController();
  DateTime? _date;
  TimeOfDay? _time;
  String _route = '';
  String _payment = 'Карта';
  String _rideType = 'Трансфер';
  bool _roundTrip = false;
  bool _meetSign = false;
  bool _pets = false;
  bool _soberDriver = false;
  bool _music = false;
  bool _flowers = false;
  bool _coffee = false;
  List<LatLng> _roadPoints = const [];
  bool _routeLoading = false;
  String _routeInfo = '';
  int _routeRequest = 0;
  Timer? _addressTimer;
  int _addressGeneration = 0;
  String? _editingAddress;
  List<String> _addressSuggestions = const [];
  final Map<String, LatLng> _resolvedAddresses = {};
  double? _routeKm;

  LatLng? _resolve(String address) =>
      _resolvedAddresses[address.trim()] ?? _places[address.trim()];

  void _addressChanged(String side) {
    _addressTimer?.cancel();
    final query = (side == 'from' ? _from.text : _to.text).trim();
    setState(() {
      _route = '';
      _editingAddress = side;
      _addressSuggestions = _places.keys
        .where((x) => x.toLowerCase().contains(query.toLowerCase()))
        .take(5).toList();
    });
    ++_addressGeneration;
    if (query.length < 3 || !widget.enableMapTiles) return;
    final current = _addressGeneration;
    _addressTimer = Timer(const Duration(milliseconds: 450), () async {
      HttpClient? client;
      try {
        client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
        final uri = Uri.https('photon.komoot.io', '/api/', {
          'q': query, 'limit': '5', 'lang': 'en',
        });
        final req = await client.getUrl(uri).timeout(const Duration(seconds: 6));
        final res = await req.close().timeout(const Duration(seconds: 6));
        if (res.statusCode != 200) return;
        final payload = jsonDecode(await utf8.decoder.bind(res).join()
          .timeout(const Duration(seconds: 6))) as Map<String, dynamic>;
        final found = <String>[];
        for (final raw in (payload['features'] as List<dynamic>? ?? const [])) {
          final feature = raw as Map<String, dynamic>;
          final p = feature['properties'] as Map<String, dynamic>? ?? {};
          final geometry = feature['geometry'] as Map<String, dynamic>? ?? {};
          final coords = geometry['coordinates'] as List<dynamic>?;
          if (coords == null || coords.length < 2) continue;
          final name = [p['name'],p['street'],p['housenumber'],p['city'],p['country']]
            .whereType<String>().where((v)=>v.trim().isNotEmpty).toSet().join(', ');
          if (name.isEmpty) continue;
          _resolvedAddresses[name] = LatLng((coords[1] as num).toDouble(),
            (coords[0] as num).toDouble());
          found.add(name);
        }
        if (mounted && current == _addressGeneration && _editingAddress == side) {
          setState(() => _addressSuggestions = found);
        }
      } catch (_) {
        // Local city suggestions remain usable without external search.
      } finally {
        client?.close(force: true);
      }
    });
  }

  void _selectAddress(String value, String side) {
    setState(() {
      (side == 'from' ? _from : _to).text = value;
      _editingAddress = null;
      _addressSuggestions = const [];
      _route = '';
    });
    _addressTimer?.cancel();
    ++_addressGeneration;
    _updateRoadPreview();
  }

  Widget _addressSuggestionsWidget(String side) {
    if (_editingAddress != side || _addressSuggestions.isEmpty) {
      return const SizedBox.shrink();
    }
    return Column(children: [
      for (var i = 0; i < _addressSuggestions.length; i++)
        ListTile(
          key: Key('passenger-$side-suggestion-$i'),
          dense: true,
          leading: const Icon(Icons.place_outlined),
          title: Text(_addressSuggestions[i], maxLines: 2),
          onTap: () => _selectAddress(_addressSuggestions[i], side),
        ),
    ]);
  }


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
      rideType: _rideType,
      roundTrip: _roundTrip,
      services: [
        if (_meetSign) 'Встреча с табличкой',
        if (_pets) 'Животные',
        if (_soberDriver) 'Трезвый водитель',
        if (_music) 'Музыка в дорогу',
        if (_flowers) 'Цветы',
        if (_coffee) 'Кофе',
        if (_tripWishes.text.trim().isNotEmpty)
          'Пожелания пассажира: ${_tripWishes.text.trim()}',
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
    'Тракай': LatLng(54.6389, 24.9342),
    'Варшава': LatLng(52.2297, 21.0122),
    'Аэропорт Вильнюса': LatLng(54.6341, 25.2858),
  };

  /// Only an agreed fixed price is shown. Other routes remain quote-only.
  int? get _fixedPrice {
    if (_rideType != 'Трансфер') return null;
    final a = _from.text.trim().toLowerCase();
    final b = _to.text.trim().toLowerCase();
    if (a == 'вильнюс' && b == 'каунас') {
      return _roundTrip ? 190 : 130;
    }
    return null;
  }

  int? get _pricePreview {
    if (_pets || _soberDriver || _flowers || _coffee) return null;
    final fixed = _fixedPrice;
    if (fixed != null) return fixed + (_meetSign ? 15 : 0);
    final km = _routeKm;
    if (km == null || !km.isFinite || km <= 0) return null;
    // Indicative formula from legacy Euro_Baltic_Transfer.py defaults:
    // BASE_FARE=8, RATE_PER_KM=0.9, MIN_FARE=25, ROUNDTRIP_FACTOR=2.
    // These are defaults, NOT verified live taxi/transfer tariffs.
    final base = math.max(25.0, 8.0 + 0.9 * km) *
      (_roundTrip ? 2 : 1);
    return base.round() + (_meetSign ? 15 : 0);
  }

  /// Public routing service is used only for a preview of preset city routes.
  /// Failure is displayed explicitly; never pretend a straight line is a road.
  Future<void> _updateRoadPreview() async {
    final request = ++_routeRequest;
    final start = _resolve(_from.text);
    final finish = _resolve(_to.text);
    if (start == null || finish == null || !widget.enableMapTiles) {
      if (mounted) setState(() {
        _roadPoints = const [];
        _routeKm = null;
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
        _routeKm = (route['distance'] as num).toDouble() / 1000;
        _routeInfo = 'Дорожный маршрут · около $km км · демо';
      });
    } catch (_) {
      if (!mounted || request != _routeRequest) return;
      setState(() {
        _roadPoints = const [];
        _routeLoading = false;
        _routeKm = null;
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
    _addressTimer?.cancel();
    _from.dispose();
    _to.dispose();
    _tripWishes.dispose();
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
          if (widget.tripStore != null)
            IconButton(
              key: const Key('passenger-orders-button'),
              tooltip: 'Мои заказы',
              icon: const Icon(Icons.receipt_long_outlined),
              onPressed: () => Navigator.push(context, MaterialPageRoute(
                builder: (_) => PassengerOrdersDemo(
                  tripStore: widget.tripStore!))),
            ),
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
            const Text('Тип поездки', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            SegmentedButton<String>(
              key: const Key('passenger-ride-type'),
              segments: const [
                ButtonSegment(value: 'Такси', label: Text('Такси'),
                  icon: Icon(Icons.local_taxi_outlined)),
                ButtonSegment(value: 'Трансфер', label: Text('Трансфер'),
                  icon: Icon(Icons.airport_shuttle_outlined)),
              ],
              selected: {_rideType},
              onSelectionChanged: (v) => setState(() {
                _rideType = v.first;
                if (_rideType != 'Трансфер') _roundTrip = false;
              }),
            ),
            if (_rideType == 'Трансфер') ...[
              SwitchListTile(
                key: const Key('passenger-round-trip'),
                title: const Text('Туда и обратно'),
                value: _roundTrip,
                onChanged: (v) => setState(() => _roundTrip = v),
              ),
              const Text(
                'Фиксированный трансфер Вильнюс → Каунас: '
                '130 € в одну сторону, 190 € туда и обратно. '
                'Клайпеда, Варшава, Тракай и Паланга — цена по запросу, '
                'до подтверждения заявки. '
                'Без промежуточных остановок.',
                key: Key('passenger-transfer-tariffs'),
                style: TextStyle(fontSize: 12),
              ),
            ] else
              const Text(
                'Такси: стоимость рассчитывается отдельно '
                'и подтверждается до оплаты.',
                key: Key('passenger-taxi-tariffs'),
                style: TextStyle(fontSize: 12),
              ),
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
                  key: const Key('route-klaipeda'),
                  label: const Text('Вильнюс — Клайпеда'),
                  onPressed: () => _chooseRoute(
                    'Вильнюс — Клайпеда', 'Вильнюс', 'Клайпеда'),
                ),
                ActionChip(
                  key: const Key('route-trakai'),
                  label: const Text('Вильнюс — Тракай'),
                  onPressed: () => _chooseRoute(
                    'Вильнюс — Тракай', 'Вильнюс', 'Тракай'),
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
              onChanged: (_) { _addressChanged('from'); _updateRoadPreview(); },
              decoration: const InputDecoration(
                labelText: 'Откуда', prefixIcon: Icon(Icons.trip_origin),
              ),
            ),
            _addressSuggestionsWidget('from'),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('passenger-to'),
                    controller: _to,
                    onChanged: (_) { _addressChanged('to'); _updateRoadPreview(); },
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
            _addressSuggestionsWidget('to'),
            const Text('Адресные подсказки запрашиваются у внешнего сервиса Photon. '
              'Не вводи конфиденциальные адреса в демоверсии.',
              style: TextStyle(fontSize: 11)),
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
            Card(
              key: const Key('passenger-personal-trip-settings-card'),
              child: ExpansionTile(
                key: const Key('passenger-personal-trip-settings'),
                initiallyExpanded: true,
                leading: const Icon(Icons.tune),
                title: const Text('Личные настройки пассажира для поездки'),
                subtitle: const Text('Цветы, кофе и индивидуальные пожелания'),
                childrenPadding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
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
              CheckboxListTile(
                key: const Key('service-flowers'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: const Text('Цветы · стоимость по запросу'),
                value: _flowers,
                onChanged: (v) => setState(() => _flowers = v ?? false),
              ),
              CheckboxListTile(
                key: const Key('service-coffee'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: const Text('Кофе · стоимость по запросу'),
                value: _coffee,
                onChanged: (v) => setState(() => _coffee = v ?? false),
              ),
              TextField(
                key: const Key('passenger-trip-wishes'),
                controller: _tripWishes,
                maxLength: 500,
                maxLines: 3,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  labelText: 'Другие пожелания к поездке',
                  hintText: 'Например, вода без газа, тишина или помощь с багажом',
                  border: OutlineInputBorder(),
                ),
              ),
                ],
              ),
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
              price != null ? (_fixedPrice != null
                  ? 'Предварительная стоимость: $price €'
                  : 'Ориентировочная стоимость: $price € · по старой формуле, требует подтверждения')
                  : _fixedPrice != null
                    ? 'Стоимость по запросу: дополнительные услуги требуют расчёта'
                    : 'Стоимость по запросу · фиксированная цена не установлена',
              key: const Key('passenger-price-preview'),
              style: const TextStyle(
                color: gold, fontWeight: FontWeight.bold, fontSize: 16,
              ),
            ),
            const Text('Демо-расчёт по прежним коэффициентам. '
              'Окончательная цена назначается диспетчером до оплаты.',
              style: TextStyle(fontSize: 12)),
            const SizedBox(height: 12),
            Text(
              'Выбрано: $_rideType · ${_route.isNotEmpty ? _route : 'свой маршрут'} · $_payment',
              key: const Key('passenger-summary'),
            ),
            const SizedBox(height: 12),
            if (widget.tripStore != null) ...[
              Text(widget.tripStore!.statusLabel,
                  key: const Key('passenger-trip-status')),
              if (widget.tripStore!.trip != null)
                FilledButton.icon(
                  key: const Key('passenger-manage-order'),
                  onPressed: () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => PassengerOrdersDemo(
                      tripStore: widget.tripStore!))),
                  icon: const Icon(Icons.receipt_long_outlined),
                  label: const Text('Управление заказом · сообщения'),
                ),
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
