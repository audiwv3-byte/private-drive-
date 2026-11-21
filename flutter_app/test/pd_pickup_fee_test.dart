import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pd_pickup_fee.dart';

void main() {
  test('pickup is free through the first five road kilometres', () {
    expect(PdPickupFee.calculateCents(roadMetres: 0), 0);
    expect(PdPickupFee.calculateCents(roadMetres: 4999), 0);
    expect(PdPickupFee.calculateCents(roadMetres: 5000), 0);
  });

  test('extra road kilometres cost forty cents each', () {
    expect(PdPickupFee.calculateCents(roadMetres: 6000), 40);
    expect(PdPickupFee.calculateCents(roadMetres: 7000), 80);
    expect(PdPickupFee.calculateCents(roadMetres: 10000), 200);
    expect(PdPickupFee.calculateCents(roadMetres: 15000), 400);
  });

  test('fractional kilometres round to euro cents', () {
    expect(PdPickupFee.calculateCents(roadMetres: 5125), 5);
    expect(PdPickupFee.calculateCents(roadMetres: 5012), 0);
    expect(PdPickupFee.calculateCents(roadMetres: 5013), 1);
  });

  test('pickup has no maximum fee', () {
    expect(PdPickupFee.calculateCents(roadMetres: 20000), 600);
    expect(PdPickupFee.calculateCents(roadMetres: 50000), 1800);
    expect(PdPickupFee.euros(1800), '18.00 €');
  });

  test('untrustworthy measured distances are rejected', () {
    expect(() => PdPickupFee.calculateCents(roadMetres: -1), throwsArgumentError);
    expect(() => PdPickupFee.calculateCents(roadMetres: 2000001), throwsArgumentError);
  });
}
