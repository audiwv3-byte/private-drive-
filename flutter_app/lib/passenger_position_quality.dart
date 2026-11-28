const _maxPassengerPositionAge = Duration(seconds: 30);
const _maxPassengerAccuracyMetres = 50.0;

/// Time left before a passenger device fix is too old to offer as pickup.
Duration? passengerPositionValidity({
  required DateTime timestamp,
  required DateTime now,
  required double accuracy,
  required bool hasAccuracy,
}) {
  final age = now.difference(timestamp);
  if (age.isNegative ||
      age >= _maxPassengerPositionAge ||
      !hasAccuracy ||
      !accuracy.isFinite ||
      accuracy <= 0 ||
      accuracy > _maxPassengerAccuracyMetres) {
    return null;
  }
  return _maxPassengerPositionAge - age;
}
