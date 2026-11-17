import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart' show LatLng;

/// Offline-only UI preview. No routing, network, GPS, payments or real orders.
class PrivateDriveDemo extends StatelessWidget {
  const PrivateDriveDemo({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE · Демоверсия')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.verified_user_outlined, size: 50, color: Color(0xFFDDC184)),
                  const SizedBox(height: 16),
                  const Text('Выбери тестовый интерфейс', style: TextStyle(fontSize: 22)),
                  const SizedBox(height: 12),
                  const Text('Демоверсия: заказы и оплата отключены. GPS — только по разрешению.',
                      textAlign: TextAlign.center),
                  const SizedBox(height: 28),
                  FilledButton.icon(
                    key: const Key('open-passenger-preview'),
                    onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const PassengerDemo())),
                    icon: const Icon(Icons.person_outline),
                    label: const Text('Пассажир'),
                  ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    key: const Key('open-pilot-preview'),
                    onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const PilotDemo())),
                    icon: const Icon(Icons.navigation_outlined),
                    label: const Text('Кабина пилота'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class PassengerDemo extends StatelessWidget {
  const PassengerDemo({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE · Пассажир')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text('Тестовый заказ поездки', style: TextStyle(fontSize: 22)),
            const SizedBox(height: 8),
            const Text('Демонстрация. Не отправляет заказы и не списывает деньги.'),
            const SizedBox(height: 24),
            const ListTile(
              leading: Icon(Icons.trip_origin),
              title: Text('Откуда'),
              subtitle: Text('Адрес пока не выбирается'),
            ),
            const ListTile(
              leading: Icon(Icons.place_outlined),
              title: Text('Куда'),
              subtitle: Text('Адрес пока не выбирается'),
            ),
            const SizedBox(height: 24),
            const FilledButton(
              onPressed: null,
              child: Text('Заказать поездку — недоступно в демоверсии'),
            ),
          ],
        ),
      ),
    );
  }
}

/// Pilot-only foreground map; all trip controls change local demo state only.
/// In widget tests [enableMapTiles] is false: there are no tile HTTP requests.
class PilotDemo extends StatefulWidget {
  const PilotDemo({super.key, this.enableMapTiles = true, this.positions});

  final bool enableMapTiles;
  /// Synthetic stream for deterministic tests; never enabled by production.
  final Stream<LatLng>? positions;

  @override
  State<PilotDemo> createState() => _PilotDemoState();
}

class _PilotDemoState extends State<PilotDemo> {
  final MapController _map = MapController();
  StreamSubscription<Position>? _gps;
  StreamSubscription<LatLng>? _synthetic;
  LatLng? _position;
  bool _following = true;
  bool _gpsEnabled = false;
  String _gpsMessage = 'GPS выключен';
  int stage = 0;
  bool paused = false;
  static const stages = ['К пассажиру', 'В путь', 'Завершить'];
  static const labels = ['Нет активной поездки', 'Едем к пассажиру', 'Поездка выполняется'];
  static const vilnius = LatLng(54.6872, 25.2797);

  void _onPosition(LatLng value) {
    if (!mounted || !value.latitude.isFinite || !value.longitude.isFinite ||
        value.latitude.abs() > 90 || value.longitude.abs() > 180) return;
    setState(() {
      _position = value;
      _gpsMessage = 'GPS активен · только на устройстве';
    });
    if (_following && widget.enableMapTiles) _map.move(value, _map.camera.zoom);
  }

  Future<void> _enableGps() async {
    if (_gpsEnabled) return;
    // Synthetic positions never request platform permissions or network calls.
    if (widget.positions != null) {
      setState(() {
        _gpsEnabled = true;
        _gpsMessage = 'Тестовый GPS';
      });
      _synthetic = widget.positions!.listen(_onPosition);
      return;
    }
    if (!widget.enableMapTiles) return;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        if (mounted) setState(() => _gpsMessage = 'Включи геолокацию устройства');
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        if (mounted) setState(() => _gpsMessage = 'Доступ к GPS не предоставлен');
        return;
      }
      if (!mounted) return;
      setState(() {
        _gpsEnabled = true;
        _gpsMessage = 'Ожидание координат GPS…';
      });
      _gps = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 5,
        ),
      ).listen(
        (p) => _onPosition(LatLng(p.latitude, p.longitude)),
        onError: (Object error) {
          if (mounted) setState(() => _gpsMessage = 'GPS недоступен');
        },
      );
    } catch (_) {
      if (mounted) setState(() => _gpsMessage = 'GPS недоступен');
    }
  }

  void _stopGps() {
    _gps?.cancel();
    _gps = null;
    _synthetic?.cancel();
    _synthetic = null;
    setState(() {
      _gpsEnabled = false;
      _gpsMessage = 'GPS выключен';
      _position = null;
    });
  }

  void advance() {
    setState(() {
      if (stage == 2) {
        stage = 0;
        paused = false;
      } else {
        stage++;
      }
    });
  }

  @override
  void dispose() {
    _gps?.cancel();
    _synthetic?.cancel();
    _map.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [
          if (widget.enableMapTiles)
            FlutterMap(
              key: const Key('pilot-map-surface'),
              mapController: _map,
              options: MapOptions(
                initialCenter: vilnius,
                initialZoom: 14,
                onPositionChanged: (camera, hasGesture) {
                  if (hasGesture && _following && mounted) {
                    setState(() => _following = false);
                  }
                },
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'lt.privatedrive.privateDrive',
                  maxNativeZoom: 19,
                ),
                if (_position != null)
                  MarkerLayer(markers: [
                    Marker(
                      point: _position!,
                      width: 48,
                      height: 48,
                      child: const Icon(Icons.navigation, size: 38,
                          color: Color(0xFFDDC184)),
                    ),
                  ]),
                const RichAttributionWidget(
                  attributions: [
                    TextSourceAttribution('© OpenStreetMap contributors'),
                  ],
                ),
              ],
            )
          else
            const RepaintBoundary(
              child: CustomPaint(
                key: Key('pilot-map-surface'),
                painter: DemoMapPainter(),
              ),
            ),
          SafeArea(
            child: Stack(
              children: [
                Positioned(
                  top: 8,
                  left: 12,
                  child: IconButton.filledTonal(
                    key: const Key('exit-pilot-preview'),
                    tooltip: 'Назад',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.arrow_back),
                  ),
                ),
                Positioned(
                  top: 8,
                  right: 12,
                  child: Chip(
                    key: const Key('pilot-gps-status'),
                    label: Text(_gpsMessage),
                  ),
                ),
                if (_position != null && !widget.enableMapTiles)
                  const Center(
                    child: Icon(Icons.navigation, size: 44,
                        color: Color(0xFFDDC184)),
                  ),
                Positioned(
                  top: 60,
                  right: 12,
                  child: Column(
                    children: [
                      if (!_gpsEnabled)
                        FloatingActionButton.small(
                          key: const Key('pilot-enable-gps'),
                          heroTag: 'pilot-gps',
                          tooltip: 'Включить GPS',
                          onPressed: _enableGps,
                          child: const Icon(Icons.my_location),
                        )
                      else
                        FloatingActionButton.small(
                          key: const Key('pilot-disable-gps'),
                          heroTag: 'pilot-stop-gps',
                          tooltip: 'Выключить GPS',
                          onPressed: _stopGps,
                          child: const Icon(Icons.location_off),
                        ),
                      if (_gpsEnabled && _position != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: FloatingActionButton.small(
                            key: const Key('pilot-center-map'),
                            heroTag: 'pilot-center',
                            tooltip: 'Центрировать карту',
                            onPressed: () {
                              setState(() => _following = true);
                              if (widget.enableMapTiles) {
                                _map.move(_position!, _map.camera.zoom);
                              }
                            },
                            child: const Icon(Icons.gps_fixed),
                          ),
                        ),
                    ],
                  ),
                ),
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 20),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: const Color(0xE9111111),
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(paused ? 'Остановка · демо' : labels[stage],
                                key: const Key('pilot-trip-state')),
                            const SizedBox(height: 10),
                            Row(
                              children: [
                                Expanded(
                                  child: FilledButton(
                                    key: const Key('pilot-next-trip'),
                                    onPressed: paused ? null : advance,
                                    child: Text(stages[stage]),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                OutlinedButton(
                                  key: const Key('pilot-pause-trip'),
                                  onPressed: stage == 0
                                      ? null
                                      : () => setState(() => paused = !paused),
                                  child: Text(paused ? 'Продолжить' : 'Остановка'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class DemoMapPainter extends CustomPainter {
  const DemoMapPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawColor(const Color(0xFF202A29), BlendMode.src);
    final blocks = Paint()..color = const Color(0xFF2B3933);
    final roads = Paint()
      ..color = const Color(0xFF68716A)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 14;
    final minorRoads = Paint()
      ..color = const Color(0xFF43544E)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 6;
    for (var i = 0; i < 9; i++) {
      final dx = size.width * i / 8;
      final dy = size.height * i / 8;
      canvas.drawRect(Rect.fromLTWH(dx - 12, dy - 20, 65, 90), blocks);
      canvas.drawLine(Offset(dx, 0), Offset(dx + size.width * 0.17, size.height), minorRoads);
      canvas.drawLine(Offset(0, dy), Offset(size.width, dy + size.height * 0.13), minorRoads);
    }
    final path = Path()
      ..moveTo(-30, size.height * 0.8)
      ..quadraticBezierTo(size.width * 0.45, size.height * 0.6, size.width * 0.35, -20);
    canvas.drawPath(path, roads);
  }

  @override
  bool shouldRepaint(covariant DemoMapPainter oldDelegate) => false;
}
