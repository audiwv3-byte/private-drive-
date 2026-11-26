import 'dart:async';
import 'dart:math' as math;

import 'package:geolocator/geolocator.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, TargetPlatform;

/// Actual sensor fix, never synthesized from a route or map marker.
class QaGpsFix {
  const QaGpsFix(this.latitude, this.longitude, this.capturedAt);
  final double latitude;
  final double longitude;
  final int capturedAt;
}

typedef QaGpsSend = Future<void> Function(String orderId, QaGpsFix? fix, int capturedAt);

/// Single consented order; no foreground-widget dependency.
/// The server must still authorize every write and reject inactive trips.
class QaPilotGpsPublisher {
  QaPilotGpsPublisher({required this.send, required this.isAssigned,
    required this.positions, this.onStopped, this.canStart, this.checkInterval = const Duration(seconds: 10), DateTime Function()? clock})
    : _clock = clock ?? DateTime.now;
  final QaGpsSend send;
  final Future<bool> Function(String) isAssigned;
  final Stream<QaGpsFix> Function() positions;
  final void Function()? onStopped;
  final bool Function()? canStart;
  final Duration checkInterval;
  final DateTime Function() _clock;
  StreamSubscription<QaGpsFix>? _stream;
  Timer? _check;
  String? _order;
  int _generation = 0;
  int _lastSent = 0;
  Future<void>? _pending;
  Future<void>? _stopping;
  bool _checking = false;
  bool _starting = false;

  String? get orderId => _order;
  bool get busy => _starting || _stopping != null;
  int get _now => _clock().millisecondsSinceEpoch ~/ 1000;

  Future<bool> start(String orderId) async {
    if (_order != null || busy) return false;
    _starting = true;
    final generation = ++_generation;
    try {
      if (!await isAssigned(orderId) || generation != _generation ||
          canStart?.call() == false) return false;
      _order = orderId;
      _lastSent = 0;
      _stream = positions().listen(_position,
        onError: (Object _) { unawaited(stop()); },
        onDone: () { unawaited(stop()); });
      _check = Timer.periodic(checkInterval, (_) {
        unawaited(_verify());
      });
      return true;
    } catch (_) {
      await stop();
      return false;
    } finally {
      _starting = false;
    }
  }

  Future<void> _verify() async {
    final order = _order;
    if (order == null || _checking) return;
    _checking = true;
    final generation = _generation;
    try {
      if (!await isAssigned(order) && generation == _generation) await stop();
    } catch (_) {
      if (generation == _generation) await stop();
    } finally {
      _checking = false;
    }
  }

  void _position(QaGpsFix fix) {
    final order = _order;
    if (order == null || _pending != null ||
        !fix.latitude.isFinite || !fix.longitude.isFinite ||
        fix.latitude.abs() > 90 || fix.longitude.abs() > 180 ||
        fix.capturedAt < _now - 30 || fix.capturedAt > _now + 5 ||
        fix.capturedAt <= _lastSent) return;
    _lastSent = fix.capturedAt;
    final generation = _generation;
    final pending = Future<void>.sync(() => send(order, fix, fix.capturedAt));
    _pending = pending;
    unawaited(pending.then<void>((_) {
      if (identical(_pending, pending)) _pending = null;
    }, onError: (Object _, StackTrace __) {
      if (identical(_pending, pending)) _pending = null;
      if (generation == _generation) unawaited(stop());
    }));
  }

  Future<void> stop() {
    if (_stopping != null) return _stopping!;
    _generation++;
    final order = _order;
    _order = null;
    _check?.cancel();
    _check = null;
    final subscription = _stream;
    _stream = null;
    final pending = _pending;
    final lastSent = _lastSent;
    final done = _stop(order, subscription, pending, lastSent);
    _stopping = done;
    unawaited(done.then<void>((_) {
      _stopping = null;
      if (order != null) onStopped?.call();
    }));
    return done;
  }

  Future<void> _stop(String? order, StreamSubscription<QaGpsFix>? subscription,
      Future<void>? pending, int lastSent) async {
    try { await subscription?.cancel(); } catch (_) {}
    try { await pending; } catch (_) {}
    if (order != null) {
      // Serialize opt-out after the final in-flight fix. If the network or
      // trip ended first, QA27 hides stale data and deletes completed trips.
      try { await send(order, null, math.max(_now, lastSent + 1)); } catch (_) {}
    }
  }
}

/// Start from the visible pilot cabin after explicit consent/permission.
/// The persistent OS notification remains visible while the stream is active.
Future<bool> qaGpsPermission() async {
  if (!await Geolocator.isLocationServiceEnabled()) return false;
  var permission = await Geolocator.checkPermission();
  if (permission == LocationPermission.denied) {
    permission = await Geolocator.requestPermission();
  }
  return permission == LocationPermission.always ||
      permission == LocationPermission.whileInUse;
}

Stream<QaGpsFix> qaAndroidPositions() =>
    Geolocator.getPositionStream(locationSettings:
    defaultTargetPlatform == TargetPlatform.iOS
      ? AppleSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 0,
          pauseLocationUpdatesAutomatically: false,
          showBackgroundLocationIndicator: true,
          allowBackgroundLocationUpdates: true,
        )
      : AndroidSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 0,
      intervalDuration: const Duration(seconds: 5),
      foregroundNotificationConfig: const ForegroundNotificationConfig(
        notificationTitle: 'PRIVATE DRIVE',
        notificationText: 'GPS назначенной поездки передаётся диспетчеру',
        enableWakeLock: true,
        setOngoing: true,
      ),
    )).map((p) => QaGpsFix(p.latitude, p.longitude,
      p.timestamp.millisecondsSinceEpoch ~/ 1000));
