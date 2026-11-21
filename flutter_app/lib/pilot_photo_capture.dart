import 'dart:typed_data';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';

abstract class PdPilotPhotoCapture {
  Future<Uint8List?> capture();
}

/// Opens the system still camera only on an explicit user gesture.
/// No gallery selection, video, microphone or automatic upload.
class PdSystemPilotPhotoCapture implements PdPilotPhotoCapture {
  const PdSystemPilotPhotoCapture();

  @override
  Future<Uint8List?> capture() async {
    if (kIsWeb) throw UnsupportedError('Use the Android or iOS application');
    final file = await ImagePicker().pickImage(
      source: ImageSource.camera,
      preferredCameraDevice: CameraDevice.front,
      maxWidth: 1280,
      maxHeight: 1280,
      imageQuality: 85,
      requestFullMetadata: false,
    );
    if (file == null) return null;
    try {
      return await file.readAsBytes();
    } finally {
      try { await File(file.path).delete(); } catch (_) { /* OS cache cleanup fallback. */ }
    }
  }

  static Future<void> discardLostCapture() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      final lost = await ImagePicker().retrieveLostData();
      for (final file in lost.files ?? <XFile>[]) {
        try { await File(file.path).delete(); } catch (_) { /* OS cache cleanup fallback. */ }
      }
    } catch (_) { /* Camera recovery must not block application startup. */ }
  }
}
