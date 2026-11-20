import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/demo_backup.dart';
import 'package:private_drive/demo_trip_store.dart';
import 'package:private_drive/passenger_preferences_storage.dart';
import 'package:private_drive/pilot_payment_settings.dart';
import 'package:private_drive/pilot_sound_settings.dart';

class FakeBackupPrefs implements DemoBackupPreferences {
  final Map<String, Object> values = {};
  String? failOnceOn;
  @override
  Future<String?> getString(String key) async => values[key] as String?;
  @override
  Future<bool?> getBool(String key) async => values[key] as bool?;
  @override
  Future<int?> getInt(String key) async => values[key] as int?;
  void check(String key) {
    if (failOnceOn == key) {
      failOnceOn = null;
      throw StateError('Simulated write failure');
    }
  }
  @override
  Future<void> setString(String key, String value) async {
    check(key); values[key] = value;
  }
  @override
  Future<void> setBool(String key, bool value) async {
    check(key); values[key] = value;
  }
  @override
  Future<void> setInt(String key, int value) async {
    check(key); values[key] = value;
  }
  @override
  Future<void> remove(String key) async {
    check(key); values.remove(key);
  }
}

String testOrder() {
  final store = DemoTripStore();
  expect(store.create(
    from: 'DEMO Vilnius', to: 'DEMO Kaunas', paymentMethod: 'Карта',
    departure: DateTime(2026, 11, 20), services: const ['Встреча с табличкой'],
  ), isTrue);
  expect(store.assignPilot(), isTrue);
  expect(store.acceptAssignedPilot(), isTrue);
  expect(store.addPilotChatMessage('TEST: on my way'), isTrue);
  expect(store.addPassengerChatMessage('TEST: ready'), isTrue);
  final saved = store.toPersistedJson()!;
  store.dispose();
  return saved;
}

String testPassengerPreferences() => jsonEncode({
  'version': 1, 'radio': 'Без радио', 'tracks': ['', '', ''],
  'temperature': 22.0, 'music': false, 'water': true,
  'wishes': 'DEMO water', 'meetSign': false, 'pets': false,
  'soberDriver': false, 'flowers': false, 'coffee': true,
  'quietRide': true, 'luggageHelp': false,
});

DemoBackupSnapshot snapshot() => DemoBackupSnapshot(
  order: testOrder(), passengerPreferences: testPassengerPreferences(),
  pilotSoundEnabled: true, pilotSoundMelody: 2, pilotAcceptCash: false,
);

void main() {
  test('Offline test order, three role chats and preferences roundtrip', () {
    final raw = DemoBackupCodec.encode(snapshot());
    final loaded = DemoBackupCodec.decode(raw);
    final restored = DemoTripStore();
    addTearDown(restored.dispose);
    expect(restored.restorePersistedJson(loaded.order!), isTrue);
    expect(restored.pilotChatMessages, ['TEST: on my way']);
    expect(restored.passengerChatMessages, ['TEST: ready']);
    expect(restored.status, DemoTripStatus.assigned);
    expect(jsonDecode(loaded.passengerPreferences!)['wishes'], 'DEMO water');
    expect(loaded.pilotSoundMelody, 2);
    expect(loaded.pilotAcceptCash, isFalse);
    expect(raw, isNot(contains('access_token')));
    expect(raw, isNot(contains('pilotLatitude')));
  });

  test('Bit corruption or manual edits fail checksum validation', () {
    final raw = DemoBackupCodec.encode(snapshot());
    final changed = raw.replaceFirst('TEST: ready', 'TEST: wrong');
    expect(changed, isNot(raw));
    expect(() => DemoBackupCodec.decode(changed), throwsFormatException);
  });

  test('Future version, unknown fields and excess size are rejected', () {
    final raw = DemoBackupCodec.encode(snapshot());
    final v2 = jsonDecode(raw) as Map<String, dynamic>;
    v2['version'] = 2;
    expect(() => DemoBackupCodec.decode(jsonEncode(v2)),
        throwsFormatException);
    final injected = DemoBackupSnapshot(
      order: jsonEncode({...jsonDecode(testOrder()) as Map<String, dynamic>,
        'token': 'secret'}),
      passengerPreferences: testPassengerPreferences(),
      pilotSoundEnabled: true, pilotSoundMelody: 1, pilotAcceptCash: false,
    );
    expect(() => DemoBackupCodec.encode(injected), throwsFormatException);
    expect(() => DemoBackupCodec.decode('x' * (DemoBackupCodec.maxSizeBytes + 1)),
        throwsFormatException);
  });

  test('Legacy v1 order without chat archives remains importable', () {
    final order = jsonDecode(testOrder()) as Map<String, dynamic>;
    order.remove('archivedChats');
    order.remove('estimatedFareEur');
    final legacy = DemoBackupSnapshot(
      order: jsonEncode(order), passengerPreferences: null,
      pilotSoundEnabled: true, pilotSoundMelody: 0,
      pilotAcceptCash: false,
    );
    final loaded = DemoBackupCodec.decode(DemoBackupCodec.encode(legacy));
    final store = DemoTripStore();
    addTearDown(store.dispose);
    expect(store.restorePersistedJson(loaded.order!), isTrue);
  });

  test('Repository exports the current local keys without unrelated secrets',
      () async {
    final prefs = FakeBackupPrefs();
    prefs.values.addAll({
      DemoBackupRepository.orderKey: testOrder(),
      DevicePassengerPreferencesStorage.key: testPassengerPreferences(),
      PilotSoundSettings.enabledKey: false,
      PilotSoundSettings.melodyKey: 1,
      PilotPaymentSettings.cashKey: false,
      'unrelated_auth_session_token': 'DO_NOT_EXPORT',
    });
    final exported = await DemoBackupRepository(prefs).export();
    expect(exported, isNot(contains('DO_NOT_EXPORT')));
    final copy = FakeBackupPrefs();
    await DemoBackupRepository(copy).restore(exported);
    expect(copy.values[DemoBackupRepository.orderKey],
        prefs.values[DemoBackupRepository.orderKey]);
    expect(copy.values[DevicePassengerPreferencesStorage.key],
        prefs.values[DevicePassengerPreferencesStorage.key]);
    expect(copy.values[PilotSoundSettings.enabledKey], false);
    expect(copy.values[PilotSoundSettings.melodyKey], 1);
    expect(copy.values.containsKey('unrelated_auth_session_token'), isFalse);
  });

  test('Invalid import does not touch current order or settings', () async {
    final prefs = FakeBackupPrefs();
    prefs.values[DemoBackupRepository.orderKey] = testOrder();
    final before = Map<String, Object>.from(prefs.values);
    await expectLater(
      DemoBackupRepository(prefs).restore('{invalid'),
      throwsFormatException,
    );
    expect(prefs.values, before);
  });

  test('Failed import write rolls back all previously changed settings',
      () async {
    final prefs = FakeBackupPrefs();
    prefs.values.addAll({
      DemoBackupRepository.orderKey: testOrder(),
      PilotSoundSettings.enabledKey: false,
      PilotSoundSettings.melodyKey: 0,
      PilotPaymentSettings.cashKey: true,
    });
    final old = Map<String, Object>.from(prefs.values);
    prefs.failOnceOn = PilotSoundSettings.melodyKey;
    await expectLater(
      DemoBackupRepository(prefs).restore(
        DemoBackupCodec.encode(DemoBackupSnapshot(
          order: null, passengerPreferences: testPassengerPreferences(),
          pilotSoundEnabled: true, pilotSoundMelody: 2,
          pilotAcceptCash: false,
        )),
      ),
      throwsStateError,
    );
    // Rollback restores values, but absent keys are not fabricated.
    expect(prefs.values[DemoBackupRepository.orderKey],
        old[DemoBackupRepository.orderKey]);
    expect(prefs.values[DevicePassengerPreferencesStorage.key], isNull);
    expect(prefs.values[PilotSoundSettings.enabledKey], false);
    expect(prefs.values[PilotSoundSettings.melodyKey], 0);
    expect(prefs.values[PilotPaymentSettings.cashKey], true);
  });
}
