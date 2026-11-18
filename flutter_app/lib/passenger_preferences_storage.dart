import 'package:shared_preferences/shared_preferences.dart';

/// Local-only demo preferences. No user token, order, or payment details.
abstract class PassengerPreferencesStorage {
  Future<String?> read();
  Future<void> write(String json);
}

class DevicePassengerPreferencesStorage implements PassengerPreferencesStorage {
  DevicePassengerPreferencesStorage();

  static const key = 'pd_demo_passenger_preferences_v1';
  final SharedPreferencesAsync _preferences = SharedPreferencesAsync();

  @override
  Future<String?> read() => _preferences.getString(key);

  @override
  Future<void> write(String json) => _preferences.setString(key, json);
}
