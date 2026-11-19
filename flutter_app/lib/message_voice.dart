import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';

/// Plays a short spoken notification for an *incoming* chat message.
/// No message body is spoken, so private correspondence is not read aloud.
class PdMessageVoice {
  PdMessageVoice._();

  static final FlutterTts _tts = FlutterTts();
  static Future<void>? _initialization;

  static Future<void> _init() async {
    await _tts.setLanguage('ru-RU');
    await _tts.setSpeechRate(0.48);
    await _tts.setPitch(1.12);
    // Android does not reliably expose gender metadata for installed voices.
    // Prefer an explicitly female voice when its name/metadata confirms it.
    try {
      final available = await _tts.getVoices;
      if (available is List) {
        for (final raw in available) {
          if (raw is! Map) continue;
          final locale = raw['locale']?.toString() ?? '';
          final name = raw['name']?.toString() ?? '';
          final gender = raw['gender']?.toString().toLowerCase() ?? '';
          final lower = name.toLowerCase();
          if (!locale.toLowerCase().startsWith('ru') ||
              !(gender == 'female' || lower.contains('female') ||
                lower.contains('жен'))) continue;
          await _tts.setVoice({'name': name, 'locale': locale});
          break;
        }
      }
    } catch (_) {
      // Device default Russian voice remains available if enumeration fails.
    }
  }

  static Future<void> announce(String sender) async {
    try {
      _initialization ??= _init();
      await _initialization;
      await _tts.stop();
      await _tts.speak('Новое сообщение от $sender');
    } catch (error) {
      debugPrint('PD_MESSAGE_VOICE_UNAVAILABLE: $error');
    }
  }
}
