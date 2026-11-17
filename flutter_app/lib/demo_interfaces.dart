import 'package:flutter/material.dart';

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
                  const Text('Только локальный просмотр. Заказы, оплата и GPS отключены.',
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

/// Isolated pilot-only full-viewport map placeholder with local UI state.
class PilotDemo extends StatefulWidget {
  const PilotDemo({super.key});

  @override
  State<PilotDemo> createState() => _PilotDemoState();
}

class _PilotDemoState extends State<PilotDemo> {
  int stage = 0;
  bool paused = false;
  static const stages = ['К пассажиру', 'В путь', 'Завершить'];
  static const labels = ['Нет активной поездки', 'Едем к пассажиру', 'Поездка выполняется'];

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
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [
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
                const Positioned(
                  top: 12,
                  right: 12,
                  child: Chip(label: Text('ДЕМО · GPS отключён')),
                ),
                const Center(
                  child: Icon(Icons.navigation, size: 44, color: Color(0xFFDDC184)),
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
