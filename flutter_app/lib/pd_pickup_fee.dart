/// PRIVATE DRIVE paid pickup tariff. Pure quotation logic, no payments.
/// Only validated road-route metres from the assigned pilot to pickup count.
class PdPickupFee {
  static const int freeMetres = 5000;
  static const int centsPerExtraKm = 40;

  /// Returns exact euro cents, rounded to the nearest cent.
  /// No upper fee cap; never use straight-line distance or guessed metres.
  static int calculateCents({required int roadMetres}) {
    if (roadMetres < 0 || roadMetres > 2000000) {
      throw ArgumentError.value(roadMetres, 'roadMetres',
          'Expected nonnegative measured road distance up to 2000 km');
    }
    final extraMetres = roadMetres - freeMetres;
    if (extraMetres <= 0) return 0;
    return (extraMetres * centsPerExtraKm + 500) ~/ 1000;
  }

  static String euros(int cents) => '${(cents / 100).toStringAsFixed(2)} €';
}
