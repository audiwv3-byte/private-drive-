import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'pilot_offer_tone.dart';

/// Shared across pilot cabin, map and settings within this app process.
/// Audio is demo-local; Android system/media volume still applies.
class PilotSoundSettings extends ChangeNotifier {
  PilotSoundSettings._();
  static final PilotSoundSettings instance = PilotSoundSettings._();
  static const enabledKey = 'pd_pilot_order_audio_enabled_v1';
  static const melodyKey = 'pd_pilot_order_audio_melody_v1';

  bool enabled = true;
  int melody = 0;
  bool _loaded = false;

  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    try {
      final prefs = SharedPreferencesAsync();
      enabled = await prefs.getBool(enabledKey) ?? true;
      melody = (await prefs.getInt(melodyKey) ?? 0).clamp(0, 2).toInt();
      notifyListeners();
    } catch (_) {
      // Missing storage does not disable order notifications.
    }
  }

  Future<void> update({bool? soundEnabled, int? selectedMelody}) async {
    if (soundEnabled != null) enabled = soundEnabled;
    if (selectedMelody != null) melody = selectedMelody.clamp(0, 2).toInt();
    notifyListeners();
    try {
      final prefs = SharedPreferencesAsync();
      await prefs.setBool(enabledKey, enabled);
      await prefs.setInt(melodyKey, melody);
    } catch (_) {
      // The current session remains usable when storage is not available.
    }
  }
}

class PilotSoundSettingsPage extends StatefulWidget {
  const PilotSoundSettingsPage({super.key});

  @override
  State<PilotSoundSettingsPage> createState() =>
      _PilotSoundSettingsPageState();
}

class _PilotSoundSettingsPageState extends State<PilotSoundSettingsPage> {
  final PilotOfferTone _preview = PilotOfferTone();
  final PilotSoundSettings _settings = PilotSoundSettings.instance;

  @override
  void initState() {
    super.initState();
    _settings.addListener(_refresh);
    unawaited(_settings.load());
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _settings.removeListener(_refresh);
    _preview.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Звуки пилота')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SwitchListTile(
          key: const Key('pilot-sounds-enabled'),
          title: const Text('Звук входящего заказа'),
          subtitle: const Text('Выключи, чтобы новые заказы приходили без мелодии'),
          value: _settings.enabled,
          onChanged: (value) {
            _preview.stop();
            unawaited(_settings.update(soundEnabled: value));
          },
        ),
        const Divider(),
        const Text('Выбери мелодию заказа',
          style: TextStyle(fontWeight: FontWeight.bold)),
        for (var i = 0; i < 3; i++)
          RadioListTile<int>(
            key: Key('pilot-order-melody-$i'),
            title: Text(['Сигнал 1 · Двойной', 'Сигнал 2 · Тревожный',
              'Сигнал 3 · Четыре тона'][i]),
            value: i,
            groupValue: _settings.melody,
            onChanged: _settings.enabled ? (value) {
              if (value == null) return;
              unawaited(_settings.update(selectedMelody: value));
              unawaited(_preview.play(melody: value));
            } : null,
            secondary: IconButton(
              key: Key('pilot-preview-melody-$i'),
              tooltip: 'Прослушать',
              onPressed: _settings.enabled
                ? () => unawaited(_preview.play(melody: i))
                : null,
              icon: const Icon(Icons.play_circle_outline),
            ),
          ),
        const SizedBox(height: 12),
        const Text(
          'Все три мелодии воспроизводятся через медиазвук телефона. '
          'Для высокой громкости увеличь громкость мультимедиа Android.',
          style: TextStyle(fontSize: 12, color: Colors.white70),
        ),
      ],
    ),
  );
}
