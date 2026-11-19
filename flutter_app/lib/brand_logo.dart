import 'package:flutter/material.dart';

/// PRIVATE DRIVE's approved PD monogram is preserved from the bundled asset.
/// A circular crop removes its legacy square icon frame; two metallic gold
/// rings supply the approved round pilot-cabin presentation.
const privateDriveLogoAsset = 'assets/brand/private_drive_logo.webp';

class PrivateDriveBrandLogo extends StatelessWidget {
  const PrivateDriveBrandLogo({
    super.key,
    this.size = 176,
    this.circular = false,
    this.transparentBackground = false,
  });

  final double size;
  /// Use a round seal in the Pilot Cockpit, retaining the original elsewhere.
  final bool circular;
  /// Removes only the legacy black image backdrop on the sign-in screen.
  final bool transparentBackground;

  @override
  Widget build(BuildContext context) {
    final asset = Image.asset(
      transparentBackground ? 'assets/brand/private_drive_logo_transparent.png' : privateDriveLogoAsset,
      key: const Key('private-drive-brand-logo'),
      width: size,
      height: size,
      filterQuality: FilterQuality.high,
      fit: BoxFit.contain,
      gaplessPlayback: true,
    );
    if (!circular) return asset;

    final outerWidth = (size * 0.029).clamp(1.0, 4.0);
    final innerWidth = (size * 0.015).clamp(0.7, 2.0);
    return SizedBox.square(
      key: const Key('private-drive-round-logo'),
      dimension: size,
      child: ClipOval(
        child: DecoratedBox(
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            color: Color(0xFF070707),
          ),
          child: Stack(
            fit: StackFit.expand,
            children: [
              // Enlarge only within the circular clip, hiding the old
              // rounded-square border but preserving the original PD artwork.
              Transform.scale(scale: 1.30, child: asset),
              DecoratedBox(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: const Color(0xFFDEBC77),
                    width: outerWidth,
                  ),
                ),
              ),
              Padding(
                padding: EdgeInsets.all((size * 0.065).clamp(1.6, 12.0)),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: const Color(0xFF947039),
                      width: innerWidth,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
