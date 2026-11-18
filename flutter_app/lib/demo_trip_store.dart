import 'package:flutter/foundation.dart';

/// In-memory simulated trip. Never talks to production APIs or payments.
/// A single store instance is shared by demo screens in one app session.
enum DemoTripStatus { requested, assigned, approaching, underway, finished, cancelled }

class DemoTrip {
  const DemoTrip({
    required this.from,
    required this.to,
    required this.paymentMethod,
    required this.departure,
    this.rideType = 'Трансфер',
    this.roundTrip = false,
    required this.services,
  });

  final String from;
  final String to;
  final String paymentMethod;
  final DateTime departure;
  final String rideType;
  final bool roundTrip;
  final List<String> services;
}

class DemoTripStore extends ChangeNotifier {
  DemoTrip? _trip;
  DemoTripStatus? _status;
  bool _paused = false;
  bool _pilotAccepted = false;
  bool _disposed = false;
  bool _pilotOnline = false;
  double? _pilotLatitude;
  double? _pilotLongitude;
  DateTime? _pilotLastSeen;
  int? _tripRating;
  int? _serviceRating;
  final List<String> _pilotChatMessages = <String>[];
  final List<String> _passengerChatMessages = <String>[];

  DemoTrip? get trip => _trip;
  bool get pilotOnline => _pilotOnline;
  double? get pilotLatitude => _pilotLatitude;
  double? get pilotLongitude => _pilotLongitude;
  DateTime? get pilotLastSeen => _pilotLastSeen;
  int? get tripRating => _tripRating;
  int? get serviceRating => _serviceRating;

  /// Session-local state. Never invent extra pilots or publish GPS to a server.
  void setPilotOnline(bool value) {
    if (_disposed || _pilotOnline == value) return;
    _pilotOnline = value;
    if (!value) {
      _pilotLatitude = null;
      _pilotLongitude = null;
      _pilotLastSeen = null;
    }
    notifyListeners();
  }

  void updatePilotLocation(double latitude, double longitude) {
    if (_disposed || !_pilotOnline ||
        !latitude.isFinite || !longitude.isFinite ||
        latitude.abs() > 90 || longitude.abs() > 180) return;
    _pilotLatitude = latitude;
    _pilotLongitude = longitude;
    _pilotLastSeen = DateTime.now();
    notifyListeners();
  }

  bool rateFinishedTrip({required int tripStars, required int serviceStars}) {
    if (_disposed || _status != DemoTripStatus.finished ||
        _trip == null || _tripRating != null || _serviceRating != null ||
        tripStars < 1 || tripStars > 5 ||
        serviceStars < 1 || serviceStars > 5) return false;
    _tripRating = tripStars;
    _serviceRating = serviceStars;
    notifyListeners();
    return true;
  }

  List<String> get pilotChatMessages => List.unmodifiable(_pilotChatMessages);
  List<String> get passengerChatMessages => List.unmodifiable(_passengerChatMessages);

  bool addPilotChatMessage(String value) {
    final message = value.trim();
    if (_disposed || message.isEmpty || message.length > 500 ||
        !_pilotAccepted ||
        (_status != DemoTripStatus.assigned &&
         _status != DemoTripStatus.approaching &&
         _status != DemoTripStatus.underway)) return false;
    _pilotChatMessages.add(message);
    notifyListeners();
    return true;
  }

  bool addPassengerChatMessage(String value) {
    final message = value.trim();
    if (_disposed || message.isEmpty || message.length > 500 ||
        !_pilotAccepted ||
        (_status != DemoTripStatus.assigned &&
         _status != DemoTripStatus.approaching &&
         _status != DemoTripStatus.underway)) return false;
    _passengerChatMessages.add(message);
    notifyListeners();
    return true;
  }
  DemoTripStatus? get status => _status;
  bool get paused => _paused;
  bool get pilotAccepted => _pilotAccepted;
  bool get isActive => _status != null &&
      _status != DemoTripStatus.finished &&
      _status != DemoTripStatus.cancelled;

  String get statusLabel => switch (_status) {
    null => 'Нет тестового заказа',
    DemoTripStatus.requested => 'Заявка создана · ожидает назначения',
    DemoTripStatus.assigned => _pilotAccepted
        ? 'Заказ принят · пилот готов к выезду'
        : 'Пилот назначен · ожидает принятия',
    DemoTripStatus.approaching => _paused
        ? 'Остановка · демо'
        : 'Пилот едет к пассажиру',
    DemoTripStatus.underway => _paused
        ? 'Остановка · демо'
        : 'Поездка выполняется',
    DemoTripStatus.finished => 'Поездка завершена · демо',
    DemoTripStatus.cancelled => 'Заказ отменён пассажиром · демо',
  };

  bool create({
    required String from,
    required String to,
    required String paymentMethod,
    required DateTime departure,
    required List<String> services,
    String rideType = 'Трансфер',
    bool roundTrip = false,
  }) {
    final a = from.trim();
    final b = to.trim();
    if (_disposed || isActive || a.isEmpty || b.isEmpty ||
        a.toLowerCase() == b.toLowerCase()) return false;
    _trip = DemoTrip(
      from: a,
      to: b,
      paymentMethod: paymentMethod,
      departure: departure,
      rideType: rideType,
      roundTrip: roundTrip,
      services: List.unmodifiable(services),
    );
    _status = DemoTripStatus.requested;
    _pilotChatMessages.clear();
    _passengerChatMessages.clear();
    _paused = false;
    _pilotAccepted = false;
    _tripRating = null;
    _serviceRating = null;
    notifyListeners();
    return true;
  }

  /// Passenger can cancel only before pilot starts travelling to pickup.
  bool cancelByPassenger() {
    if (_disposed || _trip == null ||
        (_status != DemoTripStatus.requested &&
         _status != DemoTripStatus.assigned)) return false;
    _status = DemoTripStatus.cancelled;
    _pilotAccepted = false;
    _paused = false;
    notifyListeners();
    return true;
  }

  bool get canPassengerCancel =>
      _status == DemoTripStatus.requested ||
      _status == DemoTripStatus.assigned;

    bool assignPilot() {
    if (_disposed || _status != DemoTripStatus.requested) return false;
    _status = DemoTripStatus.assigned;
    _pilotAccepted = false;
    notifyListeners();
    return true;
  }

  /// A pilot must explicitly accept a dispatcher-assigned offline demo trip.
  bool acceptAssignedPilot() {
    if (_disposed || _status != DemoTripStatus.assigned || _pilotAccepted) {
      return false;
    }
    _pilotAccepted = true;
    notifyListeners();
    return true;
  }

  /// Declining releases the assignment; the demo dispatcher can reassign.
  bool declineAssignedPilot() {
    if (_disposed || _status != DemoTripStatus.assigned || _pilotAccepted) {
      return false;
    }
    _status = DemoTripStatus.requested;
    _pilotAccepted = false;
    notifyListeners();
    return true;
  }

  bool advancePilot() {
    if (_disposed || _paused || !_pilotAccepted) return false;
    final next = switch (_status) {
      DemoTripStatus.assigned => DemoTripStatus.approaching,
      DemoTripStatus.approaching => DemoTripStatus.underway,
      DemoTripStatus.underway => DemoTripStatus.finished,
      _ => null,
    };
    if (next == null) return false;
    _status = next;
    notifyListeners();
    return true;
  }

  bool togglePause() {
    if (_disposed ||
        (_status != DemoTripStatus.approaching &&
         _status != DemoTripStatus.underway)) return false;
    _paused = !_paused;
    notifyListeners();
    return true;
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
