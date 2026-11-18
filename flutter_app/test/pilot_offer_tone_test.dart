import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pilot_offer_tone.dart';

void main() {
  test('Offer sound is a non-silent 16-bit PCM two-tone waveform', () {
    final bytes = createPilotOfferTone();
    expect(String.fromCharCodes(bytes.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(bytes.sublist(8, 12)), 'WAVE');
    expect(String.fromCharCodes(bytes.sublist(36, 40)), 'data');
    final view = ByteData.sublistView(bytes);
    expect(view.getUint16(20, Endian.little), 1);
    expect(view.getUint16(22, Endian.little), 1);
    expect(view.getUint32(24, Endian.little), 16000);
    expect(view.getUint32(40, Endian.little), bytes.length - 44);
    expect(bytes.length, greaterThan(30000));
    var peak = 0;
    for (var i = 44; i < bytes.length; i += 2) {
      final value = view.getInt16(i, Endian.little).abs();
      if (value > peak) peak = value;
    }
    expect(peak, greaterThan(14000),
      reason: 'Media-stream alarm must have audible amplitude.');
  });
}
