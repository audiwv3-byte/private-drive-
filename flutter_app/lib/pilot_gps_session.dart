import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'demo_trip_store.dart';

/// GPS is owned by the demo session, not by the pilot map route.
/// It keeps updating while navigating between screens in the foreground.
/// This does NOT request background-location access or start a background service.
class PilotGpsSession extends ChangeNotifier {
  PilotGpsSession(this.store, {this.enableDeviceGps = true});

  final DemoTripStore store;
  final bool enableDeviceGps;
  StreamSubscription<Position>? _subscription;
  bool _disposed = false;
  bool _permissionGranted = false;
  bool _requesting = false;
  String _status = 'GPS: требуется согласие';

  String get status => _status;
  bool get permissionGranted => _permissionGranted;

  void _statusChanged(String value) {
    if (_disposed || _status == value) return;
    _status = value;
    notifyListeners();
  }

  Future<bool> requestPermission() async {
    if (_disposed) return false;
    if (!enableDeviceGps) return false;
    if (_permissionGranted) return true;
    if (_requesting) return false;
    _requesting = true;
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        _statusChanged('Включи геолокацию Android');
        return false;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        _statusChanged('Разреши GPS в настройках Android');
        return false;
      }
      _permissionGranted = true;
      _statusChanged(store.pilotOnline
          ? 'GPS: подключение…'
          : 'GPS разрешён · выход на линию по POWER');
      if (store.pilotOnline) start();
      return true;
    } catch (_) {
      _statusChanged('GPS недоступен');
      return false;
    } finally {
      _requesting = false;
    }
  }

  void start() {
    if (_disposed || !store.pilotOnline) return;
    if (!enableDeviceGps) return;
    if (!_permissionGranted) {
      unawaited(requestPermission());
      return;
    }
    if (_subscription != null) return;
    _statusChanged('Ожидание координат GPS…');
    _subscription = Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 5,
      ),
    ).listen(
      (position) {
        if (_disposed || !store.pilotOnline) return;
        store.updatePilotLocation(position.latitude, position.longitude);
        _statusChanged('GPS активен');
      },
      onError: (Object error) {
        _statusChanged('GPS недоступен');
        _subscription?.cancel();
        _subscription = null;
      },
    );
  }

  void stop() {
    _subscription?.cancel();
    _subscription = null;
    store.setPilotOnline(false);
    _statusChanged(_permissionGranted
        ? 'GPS разрешён · пилот не на линии'
        : 'GPS: требуется согласие');
  }

  @override
  void dispose() {
    _disposed = true;
    _subscription?.cancel();
    _subscription = null;
    super.dispose();
  }
}
