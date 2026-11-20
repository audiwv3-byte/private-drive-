import 'package:flutter/material.dart';

/// Bright, offline PRIVATE DRIVE city artwork for public sign-in only.
/// Contains no baked-in text, buttons or personal data.
class PrivateDriveBrightBackdrop extends StatelessWidget {
  const PrivateDriveBrightBackdrop({super.key});

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: Stack(
      fit: StackFit.expand,
      children: [
        Image.asset(
          'assets/brand/private_drive_vilnius_bright.webp',
          key: const Key('private-drive-bright-auth-background'),
          fit: BoxFit.cover,
          alignment: Alignment.center,
          filterQuality: FilterQuality.medium,
        ),
        const DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Color(0x50070C18),
                Color(0x9908101A),
                Color(0xB5080C15),
              ],
              stops: [0, 0.42, 1],
            ),
          ),
        ),
      ],
    ),
  );
}
