/// PRIVATE DRIVE taxi tariff, isolated from all fixed transfer prices.
/// All arithmetic is integer euro cents. No payment network calls.
class PdTaxiFare {
  static const int boardingCents = 99;
  static const int cityCentsPerKm = 66;
  static const int outsideCityCentsPerKm = 79;
  static const int minimumCents = 400;
  static const int advanceBookingCents = 300;
  static const int largeVehicleCents = 300;
  static const int freeWaitingSeconds = 180;
  static const int waitingCentsPerMinute = 30;

  /// Road distance in metres, never a straight-line GPS estimate.
  /// City and outside-city distances must be grounded in the route;
  /// calling code must not guess the split.
  static int calculate({
    required int cityMetres,
    required int outsideCityMetres,
    bool advanceBooking = false,
    bool largeVehicle = false,
    int paidWaitingStartedMinutes = 0,
  }) {
    if (cityMetres < 0 || outsideCityMetres < 0 ||
        cityMetres + outsideCityMetres == 0 ||
        cityMetres + outsideCityMetres > 2000000 ||
        paidWaitingStartedMinutes < 0 || paidWaitingStartedMinutes > 10080) {
      throw ArgumentError('Invalid taxi route or waiting duration');
    }
    // Round the total distance contribution once, to the nearest cent.
    final distanceCents = (cityMetres * cityCentsPerKm +
        outsideCityMetres * outsideCityCentsPerKm + 500) ~/ 1000;
    final base = boardingCents + distanceCents;
    return (base < minimumCents ? minimumCents : base) +
        (advanceBooking ? advanceBookingCents : 0) +
        (largeVehicle ? largeVehicleCents : 0) +
        paidWaitingStartedMinutes * waitingCentsPerMinute;
  }

  static String euros(int cents) => '${(cents / 100).toStringAsFixed(2)} €';
}
