import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/taxi_fare.dart';

void main() {
  test('Approved city tariff and minimum use euro cents', () {
    expect(PdTaxiFare.calculate(cityMetres: 1000, outsideCityMetres: 0), 400);
    expect(PdTaxiFare.calculate(cityMetres: 10000, outsideCityMetres: 0), 759);
    expect(PdTaxiFare.calculate(cityMetres: 5000, outsideCityMetres: 0), 429);
    expect(PdTaxiFare.euros(429), '4.29 €');
  });

  test('Suburban rate and separately selected surcharges', () {
    expect(PdTaxiFare.calculate(cityMetres: 0, outsideCityMetres: 10000), 889);
    expect(PdTaxiFare.calculate(
      cityMetres: 5000, outsideCityMetres: 10000,
      advanceBooking: true), 1519);
    expect(PdTaxiFare.calculate(
      cityMetres: 5000, outsideCityMetres: 0,
      paidWaitingStartedMinutes: 2), 489);
  });

  test('No imaginary distances, negative waiting or arbitrary 10% discount', () {
    expect(() => PdTaxiFare.calculate(cityMetres: 0, outsideCityMetres: 0),
      throwsArgumentError);
    expect(() => PdTaxiFare.calculate(cityMetres: -1, outsideCityMetres: 2000),
      throwsArgumentError);
    expect(() => PdTaxiFare.calculate(
      cityMetres: 1500, outsideCityMetres: 0,
      paidWaitingStartedMinutes: -1), throwsArgumentError);
    expect(PdTaxiFare.calculate(cityMetres: 10000, outsideCityMetres: 0), 759);
  });
}
