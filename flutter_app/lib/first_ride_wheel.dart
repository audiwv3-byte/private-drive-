import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'native_orders_api.dart';

class FirstRideWheel extends StatefulWidget {
  const FirstRideWheel({super.key, required this.api, required this.onBook});
  final NativeOrdersApi api;
  final VoidCallback onBook;

  @override
  State<FirstRideWheel> createState() => _FirstRideWheelState();
}

class _FirstRideWheelState extends State<FirstRideWheel> {
  Map<String, dynamic>? reward;
  bool spinning = false;
  String? error;
  bool loading = true;
  double turns = 0;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load({bool spin = false}) async {
    if (spin) {
      setState(() {
        spinning = true;
        error = null;
      });
    }
    try {
      final result = await widget.api.firstRideWheel(spin: spin);
      if (!mounted) return;
      final sector = const {5: 0, 10: 1, 15: 2, 20: 3}[result?['percent']];
      if (spinning && sector != null && result?['state'] == 'available' &&
          !MediaQuery.disableAnimationsOf(context)) {
        setState(() => turns = turns.ceilToDouble() + 4 - sector / 4);
        await Future<void>.delayed(const Duration(milliseconds: 850));
      }
      if (mounted) {
        setState(() {
          reward = result;
          if (!spin && sector != null) turns = -sector / 4;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => error = 'Не удалось обновить скидку. Попробуй ещё раз.');
      }
    } finally {
      if (mounted) {
        setState(() {
          spinning = false;
          loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = reward?['state'];
    if (loading) return const Center(child: CircularProgressIndicator());
    if (state == null) {
      return Text(error ?? 'Колесо пока недоступно.');
    }
    if (state == 'ineligible') return const Text('Колесо доступно до первого заказа.');
    final percent = reward?['percent'];
    final expiry = reward?['expires_at'];
    final until = expiry is int
        ? MaterialLocalizations.of(context)
            .formatMediumDate(DateTime.fromMillisecondsSinceEpoch(expiry * 1000))
        : '';
    final message = switch (state) {
      'available' => 'Твоя скидка — $percent%. Действует до $until.',
      'used' => 'Скидка $percent% уже применена.',
      'expired' => 'Срок скидки истёк.',
      _ => 'Один бесплатный прокрут. Скидка от 5% до 20%.',
    };
    return Card(child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(children: [
        Text('Колесо первой поездки', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        const Icon(Icons.arrow_drop_down, color: Color(0xffeac778)),
        AnimatedRotation(
          turns: turns,
          duration: const Duration(milliseconds: 850),
          curve: Curves.easeOutCubic,
          child: const SizedBox.square(
            dimension: 118,
            child: CustomPaint(painter: _WheelPainter()),
          ),
        ),
        const SizedBox(height: 8),
        Semantics(liveRegion: true, child: Text(error ?? message)),
        if (state == 'ready') FilledButton(
          onPressed: spinning ? null : () => load(spin: true),
          child: Text(spinning ? 'Крутим…' : 'Крутить колесо'),
        ),
        if (state == 'available') FilledButton(
          onPressed: widget.onBook,
          child: const Text('Заказать со скидкой'),
        ),
      ]),
    ));
  }
}

class _WheelPainter extends CustomPainter {
  const _WheelPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.width / 2;
    const colors = [Color(0xffeac778), Color(0xff795a2b)];
    const labels = ['5%', '10%', '15%', '20%'];
    for (var sector = 0; sector < labels.length; sector++) {
      final angle = math.pi * (sector - 1) / 2;
      canvas.drawArc(Rect.fromCircle(center: center, radius: radius),
        angle - math.pi / 4, math.pi / 2, true, Paint()..color = colors[sector % 2]);
      final text = TextPainter(text: TextSpan(text: labels[sector],
        style: TextStyle(fontWeight: FontWeight.bold,
          color: sector.isEven ? const Color(0xff241908) : Colors.white)),
        textDirection: TextDirection.ltr)..layout();
      final point = center + Offset(math.cos(angle), math.sin(angle)) * radius * .67;
      text.paint(canvas, point - Offset(text.width / 2, text.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant _WheelPainter oldDelegate) => false;
}
