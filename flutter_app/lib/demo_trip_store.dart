import 'dart:convert';

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
    this.estimatedFareEur,
    this.extrasRequireQuote = false,
    required this.services,
  });

  final String from;
  final String to;
  final String paymentMethod;
  final DateTime departure;
  final String rideType;
  final bool roundTrip;
  /// Approved known fare component only; null when no fixed fare exists.
  final int? estimatedFareEur;
  /// True when additional selected services still require dispatcher pricing.
  final bool extrasRequireQuote;
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
    int? estimatedFareEur,
    bool extrasRequireQuote = false,
  }) {
    final a = from.trim();
    final b = to.trim();
    if (estimatedFareEur != null &&
        (estimatedFareEur < 0 || estimatedFareEur > 1000000)) return false;
    if (_disposed || isActive || a.isEmpty || b.isEmpty ||
        a.toLowerCase() == b.toLowerCase()) return false;
    _trip = DemoTrip(
      from: a,
      to: b,
      paymentMethod: paymentMethod,
      departure: departure,
      rideType: rideType,
      roundTrip: roundTrip,
      estimatedFareEur: estimatedFareEur,
      extrasRequireQuote: extrasRequireQuote,
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


  /// JSON contains only the simulated order, status and demo messages.
  /// Pilot GPS and sign-in credentials are deliberately never persisted.
  String? toPersistedJson() {
    final trip = _trip;
    final status = _status;
    if (trip == null || status == null) return null;
    return jsonEncode({
      'version': 1,
      'from': trip.from,
      'to': trip.to,
      'paymentMethod': trip.paymentMethod,
      'departure': trip.departure.toIso8601String(),
      'rideType': trip.rideType,
      'roundTrip': trip.roundTrip,
      'estimatedFareEur': trip.estimatedFareEur,
      'extrasRequireQuote': trip.extrasRequireQuote,
      'services': trip.services,
      'status': status.name,
      'paused': _paused,
      'pilotAccepted': _pilotAccepted,
      'tripRating': _tripRating,
      'serviceRating': _serviceRating,
      'pilotChatMessages': _pilotChatMessages,
      'passengerChatMessages': _passengerChatMessages,
    });
  }

  /// Return false for invalid/obsolete snapshots without changing the store.
  bool restorePersistedJson(String raw) {
    if (_disposed || _trip != null) return false;
    try {
      final data = jsonDecode(raw);
      if (data is! Map<String, dynamic> || data['version'] != 1) {
        return false;
      }
      final from = data['from'];
      final to = data['to'];
      final payment = data['paymentMethod'];
      final departure = data['departure'];
      final rideType = data['rideType'];
      final roundTrip = data['roundTrip'];
      final services = data['services'];
      final estimatedFareEur = data['estimatedFareEur'];
      final extrasRequireQuote = data['extrasRequireQuote'];
      final statusName = data['status'];
      if (from is! String || from.trim().isEmpty ||
          to is! String || to.trim().isEmpty ||
          from.trim().toLowerCase() == to.trim().toLowerCase() ||
          payment is! String || departure is! String ||
          rideType is! String || roundTrip is! bool ||
          services is! List || services.any((v) => v is! String) ||
          statusName is! String ||
          (estimatedFareEur != null &&
              (estimatedFareEur is! int || estimatedFareEur < 0 ||
               estimatedFareEur > 1000000)) ||
          (extrasRequireQuote != null && extrasRequireQuote is! bool)) {
        return false;
      }
      final status = DemoTripStatus.values.where((s) => s.name == statusName);
      if (status.isEmpty) return false;
      final parsedDate = DateTime.tryParse(departure);
      if (parsedDate == null) return false;
      final pilotMessages = data['pilotChatMessages'];
      final passengerMessages = data['passengerChatMessages'];
      if (pilotMessages is! List || passengerMessages is! List ||
          pilotMessages.any((v) => v is! String || v.length > 500) ||
          passengerMessages.any((v) => v is! String || v.length > 500)) {
        return false;
      }
      final tripRating = data['tripRating'];
      final serviceRating = data['serviceRating'];
      if ((tripRating != null && (tripRating is! int || tripRating < 1 || tripRating > 5)) ||
          (serviceRating != null && (serviceRating is! int || serviceRating < 1 || serviceRating > 5))) return false;
      _trip = DemoTrip(from: from.trim(), to: to.trim(),
        paymentMethod: payment, departure: parsedDate, rideType: rideType,
        roundTrip: roundTrip,
        estimatedFareEur: estimatedFareEur as int?,
        extrasRequireQuote: extrasRequireQuote == true,
        services: List<String>.unmodifiable(services.cast<String>()));
      _status = status.first;
      _paused = data['paused'] == true &&
          (_status == DemoTripStatus.approaching || _status == DemoTripStatus.underway);
      _pilotAccepted = data['pilotAccepted'] == true &&
          (_status == DemoTripStatus.assigned ||
           _status == DemoTripStatus.approaching ||
           _status == DemoTripStatus.underway ||
           _status == DemoTripStatus.finished);
      _tripRating = tripRating as int?;
      _serviceRating = serviceRating as int?;
      _pilotChatMessages..clear()..addAll(pilotMessages.cast<String>());
      _passengerChatMessages..clear()..addAll(passengerMessages.cast<String>());
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
