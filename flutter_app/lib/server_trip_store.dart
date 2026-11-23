part of 'demo_trip_store.dart';

/// Adapts the isolated API to the existing cabinet widgets. Only confirmed
/// snapshots update orders and chat. The pilot's own GPS remains responsive.
class ServerTripStore extends DemoTripStore {
  ServerTripStore(
    this._api,
    this._role, {
    Duration interval = const Duration(seconds: 2),
  }) {
    _poll = Timer.periodic(interval, (_) => refresh());
    unawaited(refresh());
  }

  final RemoteTripGateway _api;
  final String _role;
  late final Timer _poll;
  Future<void> _tail = Future.value();
  Future<void> _passengerLocationWrites = Future.value();
  String? _sharedPassengerTripId;
  bool _reading = false;
  bool _writing = false;
  bool _verified = false;
  bool _gpsDirty = false;
  bool _gpsSending = false;
  final _random = Random.secure();
  final _pendingMessages = <String, String>{};
  String? _id;
  int _version = 0;
  int _cursor = 0;
  String? _error;

  @override
  bool get serverBacked => true;

  @override
  String? get syncError => _error;

  void _report(Object error) {
    if (_disposed) return;
    final seen = _pilotLastSeen;
    if (_role != 'pilot' &&
        seen != null &&
        DateTime.now().difference(seen) >= const Duration(seconds: 90)) {
      _pilotOnline = false;
      _pilotLatitude = _pilotLongitude = null;
      _pilotLastSeen = null;
    }
    final status = error is RemoteDemoException ? error.status : null;
    _error = switch (status) {
      401 => 'Сессия истекла. Войди в кабинет снова.',
      403 => 'У аккаунта нет доступа к этой операции.',
      409 => 'Состояние заказа изменилось. Проверь его и повтори действие.',
      400 => 'Сервер отклонил данные. Проверь введённые значения.',
      _ => 'Связь с тестовым сервером потеряна. Повтори действие после восстановления.',
    };
    notifyListeners();
  }

  Future<void> _verify() async {
    if (_verified) return;
    final me = await _api.get('/v1/me');
    if (me['demo'] != true || me['role'] != _role) {
      throw const RemoteDemoException('unexpected_session_role', 403);
    }
    _verified = true;
  }

  Future<void> refresh() async {
    if (_disposed || _reading || _writing) return;
    _reading = true;
    final task = _tail.then((_) async {
      if (_disposed) return;
      try {
        await _verify();
        await _pull();
        if (_disposed) return;
        if (_error != null) {
          _error = null;
          notifyListeners();
        }
      } catch (error) {
        _report(error);
      }
    });
    _tail = task;
    try {
      await task;
    } finally {
      _reading = false;
    }
    if (_gpsDirty) _sendGps();
  }

  Future<void> _pull() async {
    final response = await _api.get('/v1/current');
    if (_disposed) return;
    final row = response['trip'] as Map<String, dynamic>?;
    final id = row?['id'] as String?;
    if (id != null && !RegExp(r'^[a-f0-9]{32}$').hasMatch(id)) {
      throw const FormatException('Invalid trip ID');
    }
    final changed = _applyTrip(id, row);
    var gpsChanged = false;
    if (_role != 'pilot') {
      final gps = response['gps'] as Map<String, dynamic>?;
      final latitude = (gps?['latitude'] as num?)?.toDouble();
      final longitude = (gps?['longitude'] as num?)?.toDouble();
      final seen = DateTime.tryParse(gps?['seen_at'] as String? ?? '');
      final valid = _validGps(latitude, longitude) && seen != null;
      gpsChanged =
          _pilotLatitude != (valid ? latitude : null) ||
          _pilotLongitude != (valid ? longitude : null) ||
          _pilotLastSeen != (valid ? seen : null);
      _pilotLatitude = valid ? latitude : null;
      _pilotLongitude = valid ? longitude : null;
      _pilotLastSeen = valid ? seen : null;
      _pilotOnline = valid;
    }
    if (changed || gpsChanged) notifyListeners();
    if (id == null) return;
    final batch = await _api.get('/v1/trips/$id/messages?after=$_cursor');
    if (_disposed) return;
    final rows = (batch['messages'] as List).cast<Map<String, dynamic>>();
    final messages = <(int, List<String>, String)>[];
    var cursor = _cursor;
    for (final message in rows) {
      final seq = message['seq'] as int;
      final target = switch (message['role']) {
        'passenger' => _passengerChatMessages,
        'pilot' => _pilotChatMessages,
        'dispatcher' => _dispatcherChatMessages,
        _ => throw const FormatException('Unknown chat role'),
      };
      final body = message['body'] as String;
      if (seq > cursor) {
        messages.add((seq, target, body));
        cursor = seq;
      }
    }
    for (final (seq, target, body) in messages) {
      target.add(body);
      _cursor = seq;
    }
    if (messages.isNotEmpty) notifyListeners();
  }

  bool _applyTrip(String? id, Map<String, dynamic>? row) {
    final version = row?['version'] as int? ?? 0;
    if (_id == id && _version == version) return false;
    final booking = row?['booking'] as Map<String, dynamic>? ?? {};
    final newTrip = id != _id;
    if (newTrip) {
      _archivePreviousChat();
      _pilotChatMessages.clear();
      _passengerChatMessages.clear();
      _dispatcherChatMessages.clear();
      _pendingMessages.clear();
      _cursor = 0;
      _tripRating = _serviceRating = _passengerRatingByPilot = null;
      _trip = row == null
          ? null
          : DemoTrip(
              from: row['origin'] as String,
              to: row['destination'] as String,
              paymentMethod: row['payment'] as String,
              departure: DateTime.parse(
                booking['departure'] as String? ?? row['created'] as String,
              ).toLocal(),
              rideType: booking['ride_type'] as String? ?? 'Трансфер',
              roundTrip: booking['round_trip'] == true,
              advanceBooking: booking['advance_booking'] == true,
              estimatedFareEur: booking['estimated_fare_eur'] as int?,
              estimatedFareCents: booking['estimated_fare_cents'] as int?,
              extrasRequireQuote: booking['extras_require_quote'] == true,
              services: List<String>.unmodifiable(
                booking['services'] as List? ?? [],
              ),
            );
    }
    _id = id;
    _version = version;
    _status = row == null
        ? null
        : DemoTripStatus.values.byName(row['status'] as String);
    _pilotAccepted = row?['accepted'] == true;
    _paused = row?['paused'] == 1;
    _arrivalAt = DateTime.tryParse(row?['arrived_at'] as String? ?? '');
    _departureFromPickupAt = DateTime.tryParse(
      row?['departed_at'] as String? ?? '',
    );
    _stopStartedAt = DateTime.tryParse(
      row?['stop_started_at'] as String? ?? '',
    );
    _completedStops
      ..clear()
      ..addAll(
        (row?['stop_ms'] as List? ?? []).cast<int>().map(
          (ms) => Duration(milliseconds: ms),
        ),
      );
    return true;
  }

  String _requestId() => List.generate(
    16,
    (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<bool> _write(Future<void> Function() send) async {
    if (_disposed || _writing) return false;
    _writing = true;
    final task = _tail.then((_) async {
      if (_disposed) return false;
      try {
        await _verify();
        await send();
        return true;
      } catch (error) {
        _report(error);
        return false;
      }
    });
    _tail = task.then<void>((_) {});
    try {
      return await task;
    } finally {
      _writing = false;
      if (_error == null) unawaited(refresh());
    }
  }

  void _confirmTrip(Map<String, dynamic> response) {
    if (_disposed) return;
    final row = response['trip'] as Map<String, dynamic>?;
    if (_applyTrip(row?['id'] as String?, row)) notifyListeners();
  }

  String? _bookingFingerprint;
  String? _bookingId;

  @override
  Future<bool> submitBooking(DemoTrip booking) => _write(() async {
    final data = <String, dynamic>{
      'from': booking.from,
      'to': booking.to,
      'payment': booking.paymentMethod,
      'departure': booking.departure.toUtc().toIso8601String(),
      'ride_type': booking.rideType,
      'round_trip': booking.roundTrip,
      'advance_booking': booking.advanceBooking,
      'estimated_fare_eur': booking.estimatedFareEur,
      'estimated_fare_cents': booking.estimatedFareCents,
      'extras_require_quote': booking.extrasRequireQuote,
      'services': booking.services,
    };
    final fingerprint = jsonEncode(data);
    if (_bookingFingerprint != fingerprint) _bookingId = _requestId();
    _bookingFingerprint = fingerprint;
    _confirmTrip(
      await _api.post('/v1/trips', {...data, 'client_id': _bookingId}),
    );
    _bookingFingerprint = _bookingId = null;
  });

  Future<bool> _action(String endpoint, [String? action]) {
    final id = _id;
    final version = _version;
    if (id == null) return Future.value(false);
    return _write(() async {
      _confirmTrip(
        await _api.post('/v1/trips/$id/$endpoint', {
          'version': version,
          if (action != null) 'action': action,
        }),
      );
    });
  }

  @override
  Future<bool> submitAssignPilot() => _action('assign');
  @override
  Future<bool> submitCancelByPassenger() => _action('cancel');
  @override
  Future<bool> submitAcceptAssignedPilot() => _action('action', 'accept');
  @override
  Future<bool> submitDeclineAssignedPilot() => _action('action', 'decline');
  @override
  Future<bool> submitAdvancePilot() => _action('action', 'advance');
  @override
  Future<bool> submitMarkArrived() => _action('action', 'arrive');
  @override
  Future<bool> submitTogglePause() =>
      _action('action', paused ? 'resume' : 'pause');

  Future<bool> _sendMessage(String text) {
    final id = _id;
    final body = text.trim();
    if (id == null || body.isEmpty || body.length > 500)
      return Future.value(false);
    return _write(() async {
      final clientId = _pendingMessages.putIfAbsent(body, _requestId);
      await _api.post('/v1/trips/$id/messages', {
        'text': body,
        'client_id': clientId,
      });
      _pendingMessages.remove(body);
    });
  }

  @override
  Future<bool> submitAddPassengerChatMessage(String text) => _sendMessage(text);
  @override
  Future<bool> submitAddPilotChatMessage(String text) => _sendMessage(text);
  @override
  Future<bool> submitAddDispatcherChatMessage(String text) =>
      _sendMessage(text);

  static bool _validGps(double? latitude, double? longitude) =>
      latitude != null &&
      longitude != null &&
      latitude.isFinite &&
      longitude.isFinite &&
      latitude.abs() <= 90 &&
      longitude.abs() <= 180 &&
      (latitude != 0 || longitude != 0);

  @override
  void setPilotOnline(bool value) {
    if (_role != 'pilot' || pilotOnline == value) return;
    super.setPilotOnline(value);
    _gpsDirty = true;
    _sendGps();
  }

  @override
  void updatePilotLocation(double latitude, double longitude) {
    if (_role != 'pilot' || !pilotOnline || !_validGps(latitude, longitude))
      return;
    super.updatePilotLocation(latitude, longitude);
    _gpsDirty = true;
    _sendGps();
  }

  void _sendGps() {
    if (_disposed || _gpsSending) return;
    _gpsSending = true;
    _tail = _tail.then((_) async {
      try {
        while (!_disposed && _gpsDirty) {
          _gpsDirty = false;
          final seen = pilotLastSeen;
          final fresh =
              seen != null &&
              DateTime.now().difference(seen) < const Duration(seconds: 90);
          await _verify();
          await _api.post('/v1/gps', {
            'online': pilotOnline,
            if (pilotOnline && fresh) ...{
              'latitude': pilotLatitude,
              'longitude': pilotLongitude,
              'seen_at': seen.toUtc().toIso8601String(),
            },
          });
        }
      } catch (error) {
        _gpsDirty = true;
        _report(error);
      } finally {
        _gpsSending = false;
      }
    });
  }

  @override
  String? get passengerLocationTripId => _role == 'passenger' && isActive ? _id : null;

  @override
  Future<void> sharePassengerLocation(double? latitude, double? longitude) {
    if (_disposed || _role != 'passenger') return Future.value();
    final current = passengerLocationTripId;
    final sharing = _validGps(latitude, longitude) && current != null;
    final tripId = sharing ? current : _sharedPassengerTripId;
    if (tripId == null) return Future.value();
    if (sharing) _sharedPassengerTripId = tripId;
    final write = _passengerLocationWrites.then((_) async {
      try {
        if (sharing && (_disposed || passengerLocationTripId != tripId)) return;
        await _postPassengerLocation(tripId, sharing ? latitude : null, sharing ? longitude : null);
        if (!sharing && _sharedPassengerTripId == tripId) _sharedPassengerTripId = null;
      } on Exception {
        // A missed GPS update never blocks a booking. The server expires it.
      }
    });
    _passengerLocationWrites = write;
    return write;
  }

  Future<void> _postPassengerLocation(String tripId, double? latitude, double? longitude) async {
    await _api.post('/v1/trips/$tripId/passenger-position', {
      'latitude': latitude, 'longitude': longitude,
    });
  }

  @override
  void dispose() {
    _poll.cancel();
    final clearGps = _role == 'pilot' && (_verified || pilotOnline);
    super.dispose();
    unawaited(
      _tail.whenComplete(() async {
        try {
          await _passengerLocationWrites;
          final sharedTrip = _sharedPassengerTripId;
          if (sharedTrip != null) await _postPassengerLocation(sharedTrip, null, null);
          if (clearGps) await _api.post('/v1/gps', {'online': false});
        } on Exception {
          // Server expires the last fix if the client disconnects.
        } finally {
          _api.close();
        }
      }),
    );
  }
}
