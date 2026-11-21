import 'package:flutter/material.dart';
import 'brand_logo.dart';

/// Visual waiting state only. It must never imply a server-side driver search.
class PdPilotAssignmentWaiting extends StatefulWidget {
  const PdPilotAssignmentWaiting({super.key});

  @override
  State<PdPilotAssignmentWaiting> createState() =>
      _PdPilotAssignmentWaitingState();
}

class _PdPilotAssignmentWaitingState extends State<PdPilotAssignmentWaiting>
    with SingleTickerProviderStateMixin {
  late final AnimationController _rotation = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 2),
  )..repeat();

  @override
  void dispose() {
    _rotation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    return Material(
      key: const Key('passenger-pd-waiting-indicator'),
      color: const Color(0xEE10151D),
      elevation: 8,
      borderRadius: BorderRadius.circular(20),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 12),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Stack(
              alignment: Alignment.center,
              children: [
                RotationTransition(
                  turns: _rotation,
                  child: const SizedBox(
                    height: 68,
                    width: 68,
                    child: CircularProgressIndicator(
                      strokeWidth: 3,
                      valueColor: AlwaysStoppedAnimation<Color>(gold),
                    ),
                  ),
                ),
                const PrivateDriveBrandLogo(size: 51, circular: true),
              ],
            ),
            const SizedBox(width: 12),
            const Flexible(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Ожидаем назначения пилота',
                    style: TextStyle(color: gold,
                      fontWeight: FontWeight.w700)),
                  SizedBox(height: 5),
                  Text('Заявка создана · тестовый режим',
                    style: TextStyle(color: Colors.white70, fontSize: 11)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
