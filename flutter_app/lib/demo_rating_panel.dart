import 'package:flutter/material.dart';
import 'demo_trip_store.dart';

/// Rate only a completed in-memory demo trip. No personal data is transmitted.
class DemoRatingPanel extends StatefulWidget {
  const DemoRatingPanel({super.key, required this.tripStore});
  final DemoTripStore tripStore;

  @override
  State<DemoRatingPanel> createState() => _DemoRatingPanelState();
}

class _DemoRatingPanelState extends State<DemoRatingPanel> {
  int _tripStars = 0;
  int _serviceStars = 0;
  static const gold = Color(0xFFDDC184);

  Widget _stars(String title, String prefix, int selected,
      ValueChanged<int> update) {
    return Column(
      children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        Row(mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (var i = 1; i <= 5; i++)
              IconButton(
                key: Key('$prefix-$i'),
                tooltip: '$title: $i из 5',
                onPressed: () => setState(() => update(i)),
                icon: Icon(
                  selected >= i ? Icons.star : Icons.star_border,
                  color: gold, size: 27,
                ),
              ),
          ],
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.tripStore;
    if (store.status != DemoTripStatus.finished) {
      return const SizedBox.shrink();
    }
    if (store.tripRating != null && store.serviceRating != null) {
      return Card(key: const Key('passenger-rating-complete'),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text(
            'Спасибо за оценку! Поездка: ${store.tripRating}/5 · '
            'Качество сервиса: ${store.serviceRating}/5',
            textAlign: TextAlign.center),
        ));
    }
    return Card(
      key: const Key('passenger-rating-panel'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(children: [
          const Text('Оцени завершённую поездку', style: TextStyle(
            fontWeight: FontWeight.bold, fontSize: 16)),
          _stars('Поездка', 'rate-trip', _tripStars,
            (stars) => _tripStars = stars),
          _stars('Качество сервиса', 'rate-service', _serviceStars,
            (stars) => _serviceStars = stars),
          FilledButton(
            key: const Key('passenger-submit-rating'),
            onPressed: _tripStars > 0 && _serviceStars > 0
              ? () => setState(() {
                  store.rateFinishedTrip(
                    tripStars: _tripStars, serviceStars: _serviceStars);
                })
              : null,
            child: const Text('Отправить оценку · демо'),
          ),
          const Text('Тестовая оценка остаётся только на устройстве.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11)),
        ]),
      ),
    );
  }
}
