import 'package:flutter/foundation.dart';

/// In-memory simulated trip. Never talks to production APIs or payments.
/// A single store instance is shared by demo screens in one app session.
enum DemoTripStatus { requested, assigned, approaching, underway, finished }

class DemoTrip {
  const DemoTrip({
    required this.from,
    required this.to,
    required this.paymentMethod,
    required this.departure,
    required this.services,
  });

  final String from;
  final String to;
  final String paymentMethod;
  final DateTime departure;
  final List<String> services;
}

class DemoTripStore extends ChangeNotifier {
  DemoTrip? _trip;
  DemoTripStatus? _status;
  bool _paused = false;
  bool _pilotAccepted = false;
  bool _disposed = false;
  final List<String> _pilotChatMessages = <String>[];

  DemoTrip? get trip => _trip;
  List<String> get pilotChatMessages => List.unmodifiable(_pilotChatMessages);

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
  DemoTripStatus? get status => _status;
  bool get paused => _paused;
  bool get pilotAccepted => _pilotAccepted;
  bool get isActive => _status != null && _status != DemoTripStatus.finished;

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
  };

  bool create({
    required String from,
    required String to,
    required String paymentMethod,
    required DateTime departure,
    required List<String> services,
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
      services: List.unmodifiable(services),
    );
    _status = DemoTripStatus.requested;
    _pilotChatMessages.clear();
    _paused = false;
    _pilotAccepted = false;
    notifyListeners();
    return true;
  }

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
