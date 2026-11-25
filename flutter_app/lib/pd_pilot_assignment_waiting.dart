import 'package:flutter/material.dart';
import 'brand_logo.dart';

import 'app_language.dart';

class PdPilotAssignmentWaiting extends StatelessWidget {
  const PdPilotAssignmentWaiting({super.key, required this.onOpenOrder});

  final VoidCallback onOpenOrder;

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
            const PrivateDriveBrandLogo(size: 51, circular: true),
            const SizedBox(width: 12),
            Flexible(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(pdTr(context, 'Ожидаем назначения пилота',
                      'Laukiama vairuotojo paskyrimo', 'Waiting for a driver'),
                    style: const TextStyle(color: gold, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 5),
                  Text(pdTr(context, 'Заявка создана · тестовый режим',
                      'Užsakymas sukurtas · bandomasis režimas',
                      'Booking created · test mode'),
                    style: const TextStyle(color: Colors.white70, fontSize: 11)),
                  TextButton(
                    key: const Key('passenger-waiting-open-order'),
                    onPressed: onOpenOrder,
                    child: Text(pdTr(context, 'Управление заказом',
                      'Valdyti užsakymą', 'Manage booking')),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
