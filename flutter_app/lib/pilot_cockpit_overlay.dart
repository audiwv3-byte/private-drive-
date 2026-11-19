import 'package:flutter/material.dart';
import 'brand_logo.dart';
import 'pd_slide_to_confirm.dart';
import 'demo_trip_store.dart';
import 'app_language.dart';

/// In-app root overlay: follows the pilot while any pilot route is open.
/// Displays only local synthetic data; does not receive production jobs.
class PilotCockpitOverlay extends StatefulWidget {
  const PilotCockpitOverlay({
    super.key,
    required this.tripStore,
    required this.onAccept,
    required this.onDecline,
  });

  final DemoTripStore? tripStore;
  final VoidCallback onAccept;
  final VoidCallback onDecline;

  @override
  State<PilotCockpitOverlay> createState() => _PilotCockpitOverlayState();
}

class _PilotCockpitOverlayState extends State<PilotCockpitOverlay> {
  bool _expanded = false;
  static const gold = Color(0xFFDDC184);
  static const background = Color(0xEE10151D);

  int? get _fare {
    final trip = widget.tripStore?.trip;
    if (trip == null) return null;
    final from = trip.from.trim().toLowerCase();
    final to = trip.to.trim().toLowerCase();
    if (trip.rideType == 'Трансфер' &&
        from == 'вильнюс' && to == 'каунас') {
      return (trip.roundTrip ? 200 : 110) +
          (trip.services.contains('Встреча с табличкой') ? 15 : 0);
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.tripStore;
    return AnimatedBuilder(
      animation: store ?? _NoopListenable.instance,
      builder: (context, _) {
        final awaiting = store?.status == DemoTripStatus.assigned &&
            store?.pilotAccepted == false &&
            store?.cashOrderNeedsOtherPilot != true;
        final trip = store?.trip;
        final fare = _fare;
        return Stack(
          fit: StackFit.expand,
          children: [
            SafeArea(
              child: Align(
                alignment: Alignment.topCenter,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(68, 8, 68, 0),
                  child: Material(
                    color: background,
                    borderRadius: BorderRadius.circular(18),
                    child: InkWell(
                      key: const Key('pilot-cockpit-earnings-toggle'),
                      onTap: () => setState(() => _expanded = !_expanded),
                      borderRadius: BorderRadius.circular(18),
                      child: Padding(
                        padding: const EdgeInsets.all(10),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const PrivateDriveBrandLogo(size: 27, circular: true),
                                const SizedBox(width: 7),
                                Flexible(
                                  child: Text(pdLabel(context, 'Сегодня · 0,00 €'),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontWeight: FontWeight.w700,
                                      color: gold,
                                    )),
                                ),
                                Icon(
                                  _expanded ? Icons.keyboard_arrow_up
                                      : Icons.keyboard_arrow_down,
                                  color: gold, size: 21,
                                ),
                              ],
                            ),
                            if (_expanded) ...[
                              const SizedBox(height: 8),
                              Text(pdLabel(context, 'За неделю · 0,00 € · демо'),
                                style: TextStyle(fontSize: 12)),
                              Text(pdLabel(context, 'Баланс · нет подключённых выплат'),
                                textAlign: TextAlign.center,
                                style: TextStyle(fontSize: 12)),
                              Text(
                                fare == null
                                  ? pdLabel(context, 'Стоимость заказа · по запросу')
                                  : '${pdLabel(context, 'Стоимость заказа')} · $fare €',
                                style: const TextStyle(
                                  fontSize: 12, color: gold),
                              ),
                              Text(pdLabel(context, 'Доход пилота · комиссия не настроена'),
                                textAlign: TextAlign.center,
                                style: TextStyle(fontSize: 11)),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            if (awaiting && trip != null)
              SafeArea(
                child: Align(
                  alignment: Alignment.bottomCenter,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 18),
                    child: Material(
                      key: const Key('pilot-global-offer'),
                      color: background,
                      elevation: 12,
                      borderRadius: BorderRadius.circular(20),
                      child: Container(
                        decoration: BoxDecoration(
                          border: Border.all(color: gold, width: 1.2),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.notifications_active, color: gold),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(pdLabel(context, 'Входящий заказ · демо'),
                                    style: const TextStyle(
                                      color: gold,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 17)),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text('${pdLabel(context, trip.rideType)} · ${trip.from} → ${trip.to}',
                              key: const Key('pilot-global-route'),
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                fontWeight: FontWeight.w700, fontSize: 17)),
                            const SizedBox(height: 7),
                            Text(fare == null
                              ? pdLabel(context, 'Стоимость · по запросу')
                              : '${pdLabel(context, 'Стоимость')} · $fare €'),
                            Text(pdLabel(context, 'Доход пилота · требуется тариф комиссии'),
                              style: TextStyle(color: gold, fontSize: 12)),
                            Text('${pdLabel(context, 'Оплата')} · ${pdLabel(context, trip.paymentMethod)}',
                              style: const TextStyle(fontSize: 12)),
                            const SizedBox(height: 12),
                            Row(
                              children: [
                                Expanded(
                                  child: PdSlideToConfirm(
                                    key: const Key('pilot-global-accept'),
                                    thumbKey: const Key('pilot-global-accept-handle'),
                                    label: pdLabel(context, 'Принять'),
                                    enabled: awaiting,
                                    onConfirmed: widget.onAccept,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: OutlinedButton(
                                    key: const Key('pilot-global-decline'),
                                    onPressed: widget.onDecline,
                                    child: Text(pdLabel(context, 'Отклонить')),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _NoopListenable extends ChangeNotifier {
  static final instance = _NoopListenable();
}
