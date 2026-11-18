import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';

/// Offline, original two-tone alert generated in memory as PCM WAV.
/// Audio is sent to the media stream, not the often-silent Android UI alert.
Uint8List createPilotOfferTone() {
  const sampleRate = 16000;
  const durationMs = 1000;
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
    final first = time >= 0.04 && time < 0.42;
    final second = time >= 0.53 && time < 0.93;
    if (!first && !second) continue;
    final begin = first ? 0.04 : 0.53;
    final end = first ? 0.42 : 0.93;
    final edge = math.min(math.min(time - begin, end - time) / 0.03, 1.0)
        .clamp(0.0, 1.0);
    final frequency = first ? 740.0 : 980.0;
    final sound = 0.7 * math.sin(2 * math.pi * frequency * time) +
        0.2 * math.sin(2 * math.pi * frequency * 1.5 * time);
    header.setInt16(44 + i * 2, (sound * 29000 * edge).round(),
        Endian.little);
  }
  return bytes;
}

class PilotOfferTone {
  AudioPlayer? _player;
  bool _closed = false;
  bool _busy = false;
  static final Uint8List _data = createPilotOfferTone();

  Future<void> play() async {
    if (_closed || _busy) return;
    _busy = true;
    try {
      final player = _player ??= AudioPlayer();
      await player.stop();
      if (_closed) return;
      await player.play(
        BytesSource(_data, mimeType: 'audio/wav'),
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
