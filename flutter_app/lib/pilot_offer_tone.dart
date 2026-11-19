import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';

/// Offline, original two-tone alert generated in memory as PCM WAV.
/// Audio is sent to the media stream, not the often-silent Android UI alert.
Uint8List createPilotOfferTone([int melody = 0]) {
  const sampleRate = 16000;
  const durationMs = 1350;
  const count = sampleRate * durationMs ~/ 1000;
  final bytes = Uint8List(44 + count * 2);
  final header = ByteData.sublistView(bytes);

  void text(int offset, String value) {
    for (var i = 0; i < value.length; i++) {
      bytes[offset + i] = value.codeUnitAt(i);
    }
  }

  text(0, 'RIFF');
  header.setUint32(4, bytes.length - 8, Endian.little);
  text(8, 'WAVE');
  text(12, 'fmt ');
  header.setUint32(16, 16, Endian.little);
  header.setUint16(20, 1, Endian.little); // PCM
  header.setUint16(22, 1, Endian.little); // mono
  header.setUint32(24, sampleRate, Endian.little);
  header.setUint32(28, sampleRate * 2, Endian.little);
  header.setUint16(32, 2, Endian.little);
  header.setUint16(34, 16, Endian.little);
  text(36, 'data');
  header.setUint32(40, count * 2, Endian.little);

  for (var i = 0; i < count; i++) {
    final time = i / sampleRate;
    // Three distinct, intentionally prominent original chimes.
    final notes = switch (melody) {
      1 => <double>[880, 1175, 1568, 1175],
      2 => <double>[740, 988, 740, 1318],
      _ => <double>[740, 980, 1180, 980],
    };
    final noteIndex = (time / 0.32).floor();
    if (noteIndex < 0 || noteIndex >= notes.length) continue;
    final inNote = time - noteIndex * 0.32;
    if (inNote >= 0.29) continue;
    final edge = math.min(math.min(inNote, 0.29 - inNote) / 0.018, 1.0)
        .clamp(0.0, 1.0);
    final frequency = notes[noteIndex];
    final sound = 0.78 * math.sin(2 * math.pi * frequency * time) +
        0.16 * math.sin(2 * math.pi * frequency * 2 * time);
    header.setInt16(44 + i * 2,
        (sound * 28500 * edge).round(), Endian.little);
  }
  return bytes;
}

class PilotOfferTone {
  AudioPlayer? _player;
  bool _closed = false;
  bool _busy = false;
  static final List<Uint8List> _melodies = List.generate(3, createPilotOfferTone);

  Future<void> play({int melody = 0}) async {
    if (_closed || _busy) return;
    _busy = true;
    try {
      final player = _player ??= AudioPlayer();
      await player.stop();
      if (_closed) return;
      await player.play(
        BytesSource(_melodies[melody.clamp(0, 2)], mimeType: 'audio/wav'),
        volume: 1.0,
        mode: PlayerMode.mediaPlayer,
      );
    } catch (_) {
      // Missing device audio hardware must not interrupt the trip or UI.
    } finally {
      _busy = false;
    }
  }

  void stop() {
    final player = _player;
    if (player != null) {
      player.stop().catchError((Object _) {});
    }
  }

  void dispose() {
    _closed = true;
    final player = _player;
    _player = null;
    if (player != null) {
      player.dispose().catchError((Object _) {});
    }
  }
}
