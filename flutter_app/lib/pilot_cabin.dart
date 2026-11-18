import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'brand_logo.dart';
import 'pilot_cockpit_overlay.dart';
import 'demo_interfaces.dart' show PilotDemo;
import 'demo_trip_store.dart';
import 'vilnius_evening_backdrop.dart';

/// The pilot's offline demo shift control lives in the cabin, never on the map.
/// This state is local to the demo and does not change real driver availability.
class PilotCabin extends StatefulWidget {
  const PilotCabin({
    super.key,
    this.enableMapTiles = true,
    this.tripStore,
  });

  final bool enableMapTiles;
  final DemoTripStore? tripStore;

  @override
  State<PilotCabin> createState() => _PilotCabinState();
}

class _PilotCabinState extends State<PilotCabin> {
  bool _onLine = false;
  OverlayEntry? _cockpitEntry;
  Timer? _offerAlert;
  bool _hasAnnouncedOffer = false;

  bool get _pendingOffer => _onLine &&
      widget.tripStore?.status == DemoTripStatus.assigned &&
      widget.tripStore?.pilotAccepted == false;

  @override
  void initState() {
    super.initState();
    widget.tripStore?.addListener(_syncOfferSound);
  }

  void _syncOfferSound() {
    if (!_pendingOffer) {
      _offerAlert?.cancel();
      _offerAlert = null;
      _hasAnnouncedOffer = false;
      return;
    }
    if (_hasAnnouncedOffer) return;
    _hasAnnouncedOffer = true;
    SystemSound.play(SystemSoundType.alert);
    _offerAlert?.cancel();
    _offerAlert = Timer.periodic(const Duration(seconds: 4), (_) {
      if (_pendingOffer) {
        SystemSound.play(SystemSoundType.alert);
      } else {
        _offerAlert?.cancel();
        _offerAlert = null;
      }
    });
  }

  void _showCockpitOverlay() {
    if (!_onLine || !mounted || _cockpitEntry != null) return;
    _cockpitEntry = OverlayEntry(
      builder: (_) => PilotCockpitOverlay(
        tripStore: widget.tripStore,
        onAccept: () => widget.tripStore?.acceptAssignedPilot(),
        onDecline: () => widget.tripStore?.declineAssignedPilot(),
      ),
    );
    Overlay.of(context, rootOverlay: true).insert(_cockpitEntry!);
    _syncOfferSound();
  }

  void _hideCockpitOverlay() {
    _offerAlert?.cancel();
    _offerAlert = null;
    _hasAnnouncedOffer = false;
    _cockpitEntry?.remove();
    _cockpitEntry?.dispose();
    _cockpitEntry = null;
  }

  @override
  void dispose() {
    widget.tripStore?.removeListener(_syncOfferSound);
    _hideCockpitOverlay();
    super.dispose();
  }


  void _openMap() {
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => PilotDemo(
        enableMapTiles: widget.enableMapTiles,
        tripStore: widget.tripStore,
        showAssignedOffer: false,
      ),
    ));
  }

  void _toggleLine() {
    if (_onLine) {
      setState(() => _onLine = false);
      _hideCockpitOverlay();
      return;
    }
    setState(() => _onLine = true);
    _openMap();
    WidgetsBinding.instance.addPostFrameCallback((_) => _showCockpitOverlay());
  }

  @override
  Widget build(BuildContext context) {
    const red = Color(0xFFFC4654);
    const green = Color(0xFF34E88A);
    final accent = _onLine ? green : red;

    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE · Кабинет пилота')),
      body: Stack(
        fit: StackFit.expand,
        children: [
          if (!_onLine) const VilniusEveningBackdrop(),
          SafeArea(
        child: Center(
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const PrivateDriveBrandLogo(size: 86),
                  const SizedBox(height: 12),
                  const Text(
                    'КАБИНЕТ ПИЛОТА',
                    style: TextStyle(
                      color: Color(0xFFDDC184),
                      letterSpacing: 2,
                      fontWeight: FontWeight.w700,
                      fontSize: 20,
                    ),
                  ),
                  const SizedBox(height: 18),
                  Text(
                    _onLine ? 'На линии · демо' : 'Не на линии · демо',
                    key: const Key('pilot-line-status'),
                    style: TextStyle(color: accent, fontSize: 18),
                  ),
                  const SizedBox(height: 32),
                  Semantics(
                    button: true,
                    label: _onLine ? 'Уйти с линии' : 'Выйти на линию',
                    child: InkWell(
                      key: const Key('pilot-power-toggle'),
                      customBorder: const CircleBorder(),
                      onTap: _toggleLine,
                      child: Container(
                        width: 180,
                        height: 180,
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: const LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [
                              Color(0xFFE3E4E7),
                              Color(0xFF777980),
                              Color(0xFF28292C),
                              Color(0xFFB6B9BE),
                            ],
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: accent.withValues(alpha: 0.22),
                              blurRadius: 26,
                              spreadRadius: 3,
                            ),
                            const BoxShadow(
                              color: Colors.black,
                              blurRadius: 16,
                              offset: Offset(0, 8),
                            ),
                          ],
                        ),
                        child: Container(
                          padding: const EdgeInsets.all(9),
                          decoration: const BoxDecoration(
                            shape: BoxShape.circle,
                            color: Color(0xFF10151D),
                          ),
                          child: Container(
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: const RadialGradient(
                                center: Alignment(-0.35, -0.45),
                                radius: 1.2,
                                colors: [
                                  Color(0xFF354B67),
                                  Color(0xFF151E2B),
                                  Color(0xFF070B12),
                                ],
                              ),
                              border: Border.all(
                                color: const Color(0xFF525A66),
                                width: 2,
                              ),
                            ),
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Text(
                                  'POWER',
                                  style: TextStyle(
                                    color: accent,
                                    fontSize: 18,
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 1.3,
                                    shadows: [
                                      Shadow(color: accent, blurRadius: 14),
                                    ],
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Icon(
                                  Icons.power_settings_new,
                                  size: 66,
                                  color: accent,
                                  shadows: [
                                    Shadow(color: accent, blurRadius: 18),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 28),
                  Text(
                    _onLine ? 'УЙТИ С ЛИНИИ' : 'ВЫЙТИ НА ЛИНИЮ',
                    key: const Key('pilot-power-caption'),
                    style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.3,
                    ),
                  ),
                  if (_onLine) ...[
                    const SizedBox(height: 18),
                    OutlinedButton.icon(
                      key: const Key('pilot-open-map'),
                      icon: const Icon(Icons.map_outlined),
                      onPressed: _openMap,
                      label: const Text('Открыть карту'),
                    ),
                  ],
                  const SizedBox(height: 28),
                  const Text(
                    'Тестовый режим. Статус линии не отправляется на сервер.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white70, fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
        ),
          ),
        ],
      ),
    );
  }
}
