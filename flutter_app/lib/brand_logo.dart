import 'package:flutter/material.dart';

/// Official PRIVATE DRIVE PD logo, variant №1, without Toyota emblem.
/// The original 1254×1254 lossless image is bundled as an offline asset.
const privateDriveLogoAsset = 'assets/brand/private_drive_logo.webp';

class PrivateDriveBrandLogo extends StatelessWidget {
  const PrivateDriveBrandLogo({super.key, this.size = 176});
  final double size;

  @override
  Widget build(BuildContext context) => Image.asset(
    privateDriveLogoAsset,
    key: const Key('private-drive-brand-logo'),
    width: size,
    height: size,
    filterQuality: FilterQuality.high,
    fit: BoxFit.contain,
    gaplessPlayback: true,
  );
}
