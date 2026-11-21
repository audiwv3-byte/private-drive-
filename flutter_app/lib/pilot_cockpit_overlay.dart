import 'package:flutter/material.dart';
import 'brand_logo.dart';
import 'pd_two_way_offer_slider.dart';
import 'demo_trip_store.dart';
import 'app_language.dart';
import 'pilot_statistics_page.dart';

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
  bool _statisticsVisible = false;
  static const gold = Color(0xFFDDC184);
  static const background = Color(0xEE10151D);

  Future<void> _openStatistics(PilotStatisticSection section) async {
    if (_statisticsVisible) return;
    // The cockpit is a root OverlayEntry and otherwise appears above routes.
    // Temporarily hide its entire surface while a details route is open.
    setState(() => _statisticsVisible = true);
    try {
      await Navigator.of(context, rootNavigator: true).push<void>(
        MaterialPageRoute<void>(
          builder: (_) => PilotStatisticsPage(section: section),
        ),
      );
    } finally {
      if (mounted) setState(() => _statisticsVisible = false);
    }
  }

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
        if (_statisticsVisible) return const SizedBox.shrink();
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
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        InkWell(
                          key: const Key('pilot-cockpit-earnings-toggle'),
                          onTap: () => setState(() => _expanded = !_expanded),
                          borderRadius: BorderRadius.circular(18),
                          child: Padding(
                            padding: const EdgeInsets.all(10),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const PrivateDriveBrandLogo(size: 27, circular: true),
                                const SizedBox(width: 7),
                                Flexible(
                                  child: Text(pdLabel(context, 'Сегодня · Нет данных'),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
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
                          ),
                        ),
                        if (_expanded)
                          ConstrainedBox(
                            constraints: BoxConstraints(
                              maxHeight: MediaQuery.sizeOf(context).height * 0.48,
                            ),
                            child: SingleChildScrollView(
                              key: const Key('pilot-cockpit-statistics-panel'),
                              padding: const EdgeInsets.fromLTRB(10, 0, 10, 12),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  _PilotStatisticTile(
                                    tileKey: 'pilot-stat-income',
                                    onTap: () => _openStatistics(PilotStatisticSection.income),
                                    icon: Icons.euro,
                                    title: 'Доход',
                                    value: 'Нет данных',
                                  ),
                                  _PilotStatisticTile(
                                    tileKey: 'pilot-stat-acceptance',
                                    onTap: () => _openStatistics(PilotStatisticSection.acceptance),
                                    icon: Icons.call_received,
                                    title: 'Принятие заказов',
                                    value: 'Нет данных',
                                  ),
                                  _PilotStatisticTile(
                                    tileKey: 'pilot-stat-rating',
                                    onTap: () => _openStatistics(PilotStatisticSection.rating),
                                    icon: Icons.star_outline,
                                    title: 'Рейтинг пилота',
                                    value: 'Нет данных',
                                  ),
                                  _PilotStatisticTile(
                                    tileKey: 'pilot-stat-level',
                                    onTap: () => _openStatistics(PilotStatisticSection.level),
                                    icon: Icons.workspace_premium_outlined,
                                    title: 'Уровень пилота',
                                    value: 'Нет данных',
                                  ),
                                  _PilotStatisticTile(
                                    tileKey: 'pilot-stat-rewards',
                                    onTap: () => _openStatistics(PilotStatisticSection.rewards),
                                    icon: Icons.card_giftcard_outlined,
                                    title: 'Поощрения',
                                    value: 'Нет данных',
                                  ),
                                ],
                              ),
                            ),
                          ),
                      ],
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
                            PdTwoWayOfferSlider(
                              key: const Key('pilot-global-offer-swipe'),
                              acceptKey: const Key('pilot-global-accept'),
                              handleKey: const Key('pilot-global-accept-handle'),
                              declineKey: const Key('pilot-global-decline'),
                              enabled: awaiting,
                              onAccept: widget.onAccept,
                              onDecline: widget.onDecline,
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


/// Read-only preview tiles. Detail routes and authenticated statistics are
/// implemented in a later stage; no synthetic earnings or ratings are shown.
class _PilotStatisticTile extends StatelessWidget {
  const _PilotStatisticTile({
    required this.tileKey,
    required this.icon,
    required this.title,
    required this.value,
    required this.onTap,
  });

  final String tileKey;
  final IconData icon;
  final String title;
  final String value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 7),
      child: Material(
        color: const Color(0xFF1D2733),
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          key: Key(tileKey),
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0x667D683F)),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Icon(icon, color: _PilotCockpitOverlayState.gold, size: 19),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(title, style: const TextStyle(fontSize: 12)),
                ),
                const SizedBox(width: 4),
                Text(value, style: const TextStyle(
                  color: Color(0xFFDDC184),
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                )),
                const SizedBox(width: 3),
                const Icon(Icons.chevron_right, color: Color(0xFFDDC184),
                  size: 17),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NoopListenable extends ChangeNotifier {
  static final instance = _NoopListenable();
}
