import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'demo_trip_store.dart';
import 'passenger_preferences_storage.dart';
import 'pilot_payment_settings.dart';
import 'pilot_sound_settings.dart';

/// Test-only, plain-text, local backup. Never contains OTP, bearer tokens,
/// user phone, live GPS or external payment credentials. This is NOT encryption.
class DemoBackupSnapshot {
  const DemoBackupSnapshot({
    this.order,
    this.passengerPreferences,
    required this.pilotSoundEnabled,
    required this.pilotSoundMelody,
    required this.pilotAcceptCash,
  });

  final String? order;
  final String? passengerPreferences;
  final bool pilotSoundEnabled;
  final int pilotSoundMelody;
  final bool pilotAcceptCash;
}

class DemoBackupCodec {
  static const format = 'private-drive-offline-demo-backup';
  static const version = 1;
  static const maxSizeBytes = 1024 * 1024;

  // Exact fields persisted by DemoTripStore v1. No arbitrary credentials or GPS.
  static const _orderFields = <String>{
    'version', 'from', 'to', 'stops', 'paymentMethod', 'departure', 'rideType',
    'roundTrip', 'advanceBooking', 'estimatedFareEur', 'estimatedFareCents',
    'extrasRequireQuote', 'services', 'status', 'paused', 'pilotAccepted',
    'arrivalAt', 'departureFromPickupAt', 'tripRating', 'serviceRating',
    'passengerRatingByPilot', 'pilotChatMessages', 'passengerChatMessages',
    'dispatcherChatMessages', 'archivedChats',
    'stopStartedAt', 'completedStopMilliseconds',
  };

  // Exact local passenger-comfort fields; not native SMS / login preferences.
  static const _passengerFields = <String>{
    'version', 'radio', 'tracks', 'temperature', 'meetSign', 'pets',
    'soberDriver', 'music', 'flowers', 'coffee', 'water', 'quietRide',
    'luggageHelp', 'wishes',
  };

  static bool _keysAreAllowed(Map<String, dynamic> data, Set<String> keys) =>
      data.keys.every(keys.contains);

  static Map<String, dynamic> _parseObject(String raw, String label) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) return decoded;
    } catch (_) {
      // Converted to a stable format error below.
    }
    throw FormatException('Некорректный раздел: $label');
  }

  static void _validateOrder(String? raw) {
    if (raw == null) return;
    final data = _parseObject(raw, 'заказ');
    if (!_keysAreAllowed(data, _orderFields)) {
      throw const FormatException('Неизвестные поля заказа');
    }
    final archived = data['archivedChats'];
    if (archived is List) {
      const allowedChatFields = <String>{
        'from', 'to', 'pilotMessages', 'passengerMessages',
        'dispatcherMessages',
      };
      for (final item in archived) {
        if (item is! Map<String, dynamic> ||
            !_keysAreAllowed(item, allowedChatFields)) {
          throw const FormatException('Неизвестные поля архива переписки');
        }
      }
    }
    final store = DemoTripStore();
    try {
      if (!store.restorePersistedJson(raw)) {
        throw const FormatException('Несовместимый тестовый заказ');
      }
    } finally {
      store.dispose();
    }
  }

  static void _validatePassenger(String? raw) {
    if (raw == null) return;
    final data = _parseObject(raw, 'настройки пассажира');
    if (data['version'] != 1 ||
        !_keysAreAllowed(data, _passengerFields)) {
      throw const FormatException('Несовместимые настройки пассажира');
    }
    final tracks = data['tracks'];
    if (tracks != null && (tracks is! List ||
        tracks.length != 3 ||
        tracks.any((track) => track is! String || track.length > 100))) {
      throw const FormatException('Некорректные любимые треки');
    }
    final radio = data['radio'];
    final wishes = data['wishes'];
    final temperature = data['temperature'];
    if ((radio != null && (radio is! String || radio.length > 100)) ||
        (wishes != null && (wishes is! String || wishes.length > 500)) ||
        (temperature != null && (temperature is! num ||
            !temperature.isFinite || temperature < 18 || temperature > 26 ||
            temperature != temperature.roundToDouble()))) {
      throw const FormatException('Некорректные настройки комфорта');
    }
    for (final key in const <String>[
      'meetSign', 'pets', 'soberDriver', 'music', 'flowers', 'coffee',
      'water', 'quietRide', 'luggageHelp',
    ]) {
      if (data.containsKey(key) && data[key] is! bool) {
        throw const FormatException('Некорректный переключатель услуги');
      }
    }
  }

  static Map<String, dynamic> _payload(DemoBackupSnapshot value) => {
    'order': value.order,
    'passengerPreferences': value.passengerPreferences,
    'pilotSoundEnabled': value.pilotSoundEnabled,
    'pilotSoundMelody': value.pilotSoundMelody,
    'pilotAcceptCash': value.pilotAcceptCash,
  };

  static void _validate(DemoBackupSnapshot value) {
    if (value.pilotSoundMelody < 0 || value.pilotSoundMelody > 2) {
      throw const FormatException('Недопустимая мелодия пилота');
    }
    _validateOrder(value.order);
    _validatePassenger(value.passengerPreferences);
  }

  static String encode(DemoBackupSnapshot snapshot) {
    _validate(snapshot);
    final payload = _payload(snapshot);
    final checksum = sha256.convert(utf8.encode(jsonEncode(payload))).toString();
    final result = jsonEncode({
      'format': format,
      'version': version,
      'payload': payload,
      'sha256': checksum,
    });
    if (utf8.encode(result).length > maxSizeBytes) {
      throw const FormatException('Резервная копия слишком большая');
    }
    return result;
  }

  static DemoBackupSnapshot decode(String raw) {
    if (utf8.encode(raw).length > maxSizeBytes) {
      throw const FormatException('Резервная копия слишком большая');
    }
    final wrapper = _parseObject(raw, 'резервная копия');
    if (wrapper.length != 4 ||
        !wrapper.keys.toSet().containsAll(
            const <String>{'format', 'version', 'payload', 'sha256'}) ||
        wrapper['format'] != format || wrapper['version'] != version ||
        wrapper['payload'] is! Map<String, dynamic> ||
        wrapper['sha256'] is! String) {
      throw const FormatException('Неизвестная версия резервной копии');
    }
    final payload = wrapper['payload'] as Map<String, dynamic>;
    const fields = <String>{
      'order', 'passengerPreferences', 'pilotSoundEnabled',
      'pilotSoundMelody', 'pilotAcceptCash',
    };
    if (payload.length != fields.length ||
        !payload.keys.toSet().containsAll(fields) ||
        (payload['order'] != null && payload['order'] is! String) ||
        (payload['passengerPreferences'] != null &&
            payload['passengerPreferences'] is! String) ||
        payload['pilotSoundEnabled'] is! bool ||
        payload['pilotSoundMelody'] is! int ||
        payload['pilotAcceptCash'] is! bool) {
      throw const FormatException('Повреждён состав резервной копии');
    }
    final calculated = sha256.convert(utf8.encode(jsonEncode(payload))).toString();
    if (calculated != wrapper['sha256']) {
      throw const FormatException('Контрольная сумма не совпадает');
    }
    final snapshot = DemoBackupSnapshot(
      order: payload['order'] as String?,
      passengerPreferences: payload['passengerPreferences'] as String?,
      pilotSoundEnabled: payload['pilotSoundEnabled'] as bool,
      pilotSoundMelody: payload['pilotSoundMelody'] as int,
      pilotAcceptCash: payload['pilotAcceptCash'] as bool,
    );
    _validate(snapshot);
    return snapshot;
  }
}

/// Device-only storage adapter. Supports rollback when a write fails; as
/// SharedPreferences uses separate keys, this is best-effort, not ACID.
abstract class DemoBackupPreferences {
  Future<String?> getString(String key);
  Future<bool?> getBool(String key);
  Future<int?> getInt(String key);
  Future<void> setString(String key, String value);
  Future<void> setBool(String key, bool value);
  Future<void> setInt(String key, int value);
  Future<void> remove(String key);
}

class DeviceDemoBackupPreferences implements DemoBackupPreferences {
  final SharedPreferencesAsync _prefs = SharedPreferencesAsync();
  @override
  Future<String?> getString(String key) => _prefs.getString(key);
  @override
  Future<bool?> getBool(String key) => _prefs.getBool(key);
  @override
  Future<int?> getInt(String key) => _prefs.getInt(key);
  @override
  Future<void> setString(String key, String value) => _prefs.setString(key, value);
  @override
  Future<void> setBool(String key, bool value) => _prefs.setBool(key, value);
  @override
  Future<void> setInt(String key, int value) => _prefs.setInt(key, value);
  @override
  Future<void> remove(String key) => _prefs.remove(key);
}

class DemoBackupRepository {
  DemoBackupRepository(this.storage);
  final DemoBackupPreferences storage;

  static const orderKey = 'pd_offline_demo_order_v1';

  Future<DemoBackupSnapshot> read() async => DemoBackupSnapshot(
    order: await storage.getString(orderKey),
    passengerPreferences: await storage.getString(DevicePassengerPreferencesStorage.key),
    pilotSoundEnabled: await storage.getBool(PilotSoundSettings.enabledKey) ?? true,
    pilotSoundMelody: await storage.getInt(PilotSoundSettings.melodyKey) ?? 0,
    pilotAcceptCash: await storage.getBool(PilotPaymentSettings.cashKey) ?? false,
  );

  Future<String> export() async => DemoBackupCodec.encode(await read());

  Future<void> _write(DemoBackupSnapshot value) async {
    Future<void> text(String key, String? raw) async {
      if (raw == null) {
        await storage.remove(key);
      } else {
        await storage.setString(key, raw);
      }
    }
    await text(orderKey, value.order);
    await text(DevicePassengerPreferencesStorage.key, value.passengerPreferences);
    await storage.setBool(PilotSoundSettings.enabledKey, value.pilotSoundEnabled);
    await storage.setInt(PilotSoundSettings.melodyKey, value.pilotSoundMelody);
    await storage.setBool(PilotPaymentSettings.cashKey, value.pilotAcceptCash);
  }

  /// No change occurs for invalid/tampered backups. If a disk write fails,
  /// restore the prior local values before surfacing the error.
  Future<void> restore(String raw) async {
    final imported = DemoBackupCodec.decode(raw);
    final before = await read();
    try {
      await _write(imported);
      final after = await read();
      if (DemoBackupCodec.encode(after) != DemoBackupCodec.encode(imported)) {
        throw StateError('Резервная копия записана не полностью');
      }
    } catch (_) {
      try {
        await _write(before);
      } catch (_) {
        throw StateError(
          'Сбой записи и отката. Не закрывай приложение: нужна проверка данных');
      }
      rethrow;
    }
  }
}
