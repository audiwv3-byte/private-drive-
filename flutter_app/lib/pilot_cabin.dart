import 'dart:async';

import 'package:flutter/material.dart';
import 'pilot_offer_tone.dart';
import 'native_pilot_orders.dart';
import 'pilot_sound_settings.dart';
import 'pilot_payment_settings.dart';
import 'pilot_identity_notice_page.dart';
import 'pilot_identity_api.dart';
import 'brand_logo.dart';
import 'app_language.dart';
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
    this.assignmentApi,
    this.onOfferAlert,
    this.onSignOut,
    this.onBackToCabinets,
  });

  final bool enableMapTiles;
  final DemoTripStore? tripStore;
  final NativePilotOrdersApi? assignmentApi;
  final VoidCallback? onSignOut;
  final VoidCallback? onBackToCabinets;
  /// Test-only hook to verify alert repetition without device audio.
  final VoidCallback? onOfferAlert;

  @override
  State<PilotCabin> createState() => _PilotCabinState();
}

class _PilotCabinState extends State<PilotCabin> {
  bool _onLine = false;
  bool _assignmentMapOpen = false;
  OverlayEntry? _cockpitEntry;
  Timer? _offerAlert;
  bool _hasAnnouncedOffer = false;
  final PilotOfferTone _offerTone = PilotOfferTone();

  void _playOfferTone() {
    final callback = widget.onOfferAlert;
    if (callback != null) {
      callback();
    } else {
      if (PilotSoundSettings.instance.enabled) {
        unawaited(_offerTone.play(melody: PilotSoundSettings.instance.melody));
      }
    }
  }

  bool get _pendingOffer => _onLine &&
      !(widget.tripStore?.cashOrderNeedsOtherPilot ?? false) &&
      widget.tripStore?.status == DemoTripStatus.assigned &&
      widget.tripStore?.pilotAccepted == false;

  @override
  void initState() {
    super.initState();
    if (widget.assignmentApi != null) return;
    _onLine = widget.tripStore?.pilotOnline ?? false;
    widget.tripStore?.addListener(_syncOfferSound);
    PilotSoundSettings.instance.addListener(_onSettingsChanged);
    unawaited(PilotSoundSettings.instance.load());
    PilotPaymentSettings.instance.addListener(_onPaymentSettingsChanged);
    _onPaymentSettingsChanged();
    unawaited(_loadPaymentSettings());
    if (_onLine) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _openMap();
          _showCockpitOverlay();
        }
      });
    }
  }

  Future<void> _loadPaymentSettings() async {
    await PilotPaymentSettings.instance.load();
    _onPaymentSettingsChanged();
  }

  void _onPaymentSettingsChanged() {
    widget.tripStore?.setPilotAcceptsCash(
      PilotPaymentSettings.instance.acceptCash);
    _syncOfferSound();
  }

  void _onSettingsChanged() {
    if (!PilotSoundSettings.instance.enabled) _offerTone.stop();
  }

  void _syncOfferSound() {
    if (!_pendingOffer) {
      _offerAlert?.cancel();
      _offerAlert = null;
      _offerTone.stop();
      _hasAnnouncedOffer = false;
      return;
    }
    if (_hasAnnouncedOffer) return;
    _hasAnnouncedOffer = true;
    _playOfferTone();
    _offerAlert?.cancel();
    _offerAlert = Timer.periodic(const Duration(seconds: 4), (_) {
      if (_pendingOffer) {
        _playOfferTone();
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
    _offerTone.stop();
    _hasAnnouncedOffer = false;
    _cockpitEntry?.remove();
    _cockpitEntry?.dispose();
    _cockpitEntry = null;
  }

  @override
  void dispose() {
    if (widget.assignmentApi == null) {
      widget.tripStore?.removeListener(_syncOfferSound);
      PilotSoundSettings.instance.removeListener(_onSettingsChanged);
      PilotPaymentSettings.instance.removeListener(_onPaymentSettingsChanged);
      _hideCockpitOverlay();
    }
    // Leaving this screen is not the same as ending a shift.
    _offerTone.dispose();
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

  Future<void> _openAssignmentMap() async {
    if (_assignmentMapOpen || widget.assignmentApi == null) return;
    setState(() => _assignmentMapOpen = true);
    try {
      await Navigator.of(context).push<void>(MaterialPageRoute<void>(
        builder: (_) => PilotDemo.ownDevice(enableMapTiles: widget.enableMapTiles),
      ));
    } finally {
      if (mounted) setState(() => _assignmentMapOpen = false);
    }
  }

  void _toggleLine() {
    if (_onLine) {
      setState(() => _onLine = false);
      widget.tripStore?.setPilotOnline(false);
      _hideCockpitOverlay();
      return;
    }
    setState(() => _onLine = true);
    widget.tripStore?.setPilotOnline(true);
    _openMap();
    WidgetsBinding.instance.addPostFrameCallback((_) => _showCockpitOverlay());
  }

  @override
  Widget build(BuildContext context) {
    const red = Color(0xFFFC4654);
    const green = Color(0xFF34E88A);
    final accent = _onLine ? green : red;

    return Scaffold(
      appBar: AppBar(
        title: Text('PRIVATE DRIVE · ${pdLabel(context, 'Кабина пилота')}'),
        leading: widget.onBackToCabinets == null
            ? null
            : BackButton(onPressed: widget.onBackToCabinets),
        actions: [
          if (widget.assignmentApi != null)
            IconButton(
              key: const Key('pilot-server-open-map'),
              tooltip: 'Открыть карту',
              icon: const Icon(Icons.map_outlined),
              onPressed: _assignmentMapOpen ? null : _openAssignmentMap,
            ),
          if (widget.onSignOut != null)
            IconButton(
              tooltip: 'Выйти',
              icon: const Icon(Icons.logout),
              onPressed: widget.onSignOut,
            ),
        ],
      ),
      body: widget.assignmentApi != null
          ? Stack(fit: StackFit.expand, children: [
              const VilniusEveningBackdrop(),
              SafeArea(child: Column(children: [
                const SizedBox(height: 14),
                const SizedBox(
                  key: Key('pilot-connected-brand-logo'),
                  height: 86, width: 86,
                  child: PrivateDriveBrandLogo(
                    size: 86, transparentBackground: true),
                ),
                const SizedBox(height: 8),
                const Text('КАБИНА ПИЛОТА',
                  key: Key('pilot-connected-cabin-title'),
                  style: TextStyle(color: Color(0xFFDDC184),
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.8, fontSize: 19)),
                const SizedBox(height: 4),
                const Text('Заказы и статусы подтверждаются сервером',
                  style: TextStyle(color: Colors.white70, fontSize: 12)),
                const SizedBox(height: 8),
                PilotServerAvailabilityButton(api: widget.assignmentApi!),
                const SizedBox(height: 8),
                Expanded(child: PilotAssignedOrdersPanel(
                  api: widget.assignmentApi!, visible: !_assignmentMapOpen)),
              ])),
            ])
          : Stack(
        fit: StackFit.expand,
        children: [
          const VilniusEveningBackdrop(),
          SafeArea(
        child: Center(
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const SizedBox(
                    key: Key('pilot-line-transparent-logo'),
                    width: 112,
                    height: 112,
                    child: PrivateDriveBrandLogo(
                      size: 112,
                      transparentBackground: true,
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    pdLabel(context, 'КАБИНЕТ ПИЛОТА'),
                    style: const TextStyle(
                      color: Color(0xFFDDC184),
                      letterSpacing: 2,
                      fontWeight: FontWeight.w700,
                      fontSize: 20,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    pdLabel(context,
                      _onLine ? 'На линии · демо' : 'Не на линии · демо'),
                    key: const Key('pilot-line-status'),
                    style: TextStyle(color: accent, fontSize: 18),
                  ),
                  const SizedBox(height: 20),
                  Semantics(
                    button: true,
                    label: pdTr(context,
                      _onLine ? 'Уйти с линии' : 'Выйти на линию',
                      _onLine ? 'Atsijungti' : 'Prisijungti',
                      _onLine ? 'Go offline' : 'Go online'),
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
                    pdLabel(context, _onLine ? 'УЙТИ С ЛИНИИ' : 'ВЫЙТИ НА ЛИНИЮ'),
                    key: const Key('pilot-power-caption'),
                    style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.3,
                    ),
                  ),
                  const SizedBox(height: 18),
                  OutlinedButton.icon(
                    key: const Key('pilot-open-identity-check'),
                    icon: const Icon(Icons.verified_user_outlined),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => PdPilotIdentityNoticePage(
                          api: PdIdentityScope.maybeOf(context),
                          onContinueWithoutVerification: () {
                            // Never mark identity verified or change server rights.
                            Navigator.of(context).popUntil((route) => route.isFirst);
                            widget.onBackToCabinets?.call();
                          },
                        ),
                      ),
                    ),
                    label: const Text('Проверка личности · раз в 7 дней'),
                  ),
                  if (_onLine) ...[
                    const SizedBox(height: 18),
                    OutlinedButton.icon(
                      key: const Key('pilot-open-map'),
                      icon: const Icon(Icons.map_outlined),
                      onPressed: _openMap,
                      label: Text(pdLabel(context, 'Открыть карту')),
                    ),
                  ],
                  const SizedBox(height: 28),
                  Text(
                    pdLabel(context, 'Тестовый режим. Статус линии не отправляется на сервер.'),
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.white70, fontSize: 12),
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

