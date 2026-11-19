import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'demo_trip_store.dart';

/// Pilot-specific preferences for local DEMO rides only.
/// Defaults to OFF; never changes payment handling in production.
class PilotPaymentSettings extends ChangeNotifier {
  PilotPaymentSettings._();
  static final PilotPaymentSettings instance = PilotPaymentSettings._();
  static const cashKey = 'pd_pilot_accept_cash_v1';

  bool acceptCash = false;
  bool _loaded = false;

  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    try {
      acceptCash = await SharedPreferencesAsync().getBool(cashKey) ?? false;
      notifyListeners();
    } catch (_) {
      // Safer default is no cash orders if settings are unavailable.
    }
  }

  Future<void> setCash(bool enabled) async {
    acceptCash = enabled;
    notifyListeners();
    try {
      await SharedPreferencesAsync().setBool(cashKey, enabled);
    } catch (_) {
      // Local setting remains in effect for the current DEMO session.
    }
  }
}

class PilotPaymentSettingsPage extends StatefulWidget {
  const PilotPaymentSettingsPage({super.key, this.tripStore});
  final DemoTripStore? tripStore;

  @override
  State<PilotPaymentSettingsPage> createState() =>
      _PilotPaymentSettingsPageState();
}

class _PilotPaymentSettingsPageState extends State<PilotPaymentSettingsPage> {
  final _settings = PilotPaymentSettings.instance;

  @override
  void initState() {
    super.initState();
    _settings.addListener(_refresh);
    _syncFromStorage();
  }

  Future<void> _syncFromStorage() async {
    await _settings.load();
    widget.tripStore?.setPilotAcceptsCash(_settings.acceptCash);
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _settings.removeListener(_refresh);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Настройки оплаты пилота')),
    body: ListView(padding: const EdgeInsets.all(16), children: [
      SwitchListTile(
        key: const Key('pilot-accept-cash'),
        title: const Text('Принимать наличные'),
        subtitle: const Text(
          'Включи, чтобы диспетчер мог назначать тебе наличные заказы. '
          'Если выключено — такие заказы не предлагаются.'),
        value: _settings.acceptCash,
        onChanged: (enabled) {
          widget.tripStore?.setPilotAcceptsCash(enabled);
          _settings.setCash(enabled);
        },
      ),
      const SizedBox(height: 12),
      const Text(
        'Настройка действует для новых тестовых назначений. '
        'Способ оплаты уже принятого заказа не меняется. '
        'Реальные платежи и кассовый учёт здесь не выполняются.',
        style: TextStyle(fontSize: 12),
      ),
    ]),
  );
}
