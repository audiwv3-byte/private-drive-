import 'package:flutter/material.dart';

/// The actual Vilnius Cathedral photo supplied by the user, compressed as an
/// offline-only preview asset. It is never loaded from an external server.
class VilniusEveningBackdrop extends StatelessWidget {
  const VilniusEveningBackdrop({super.key});

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: Stack(
      fit: StackFit.expand,
      children: [
        Image.asset(
          'assets/brand/vilnius_cathedral_user_photo.webp',
          key: const Key('pilot-offline-vilnius-background'),
          fit: BoxFit.cover,
          alignment: const Alignment(-0.48, 0),
          filterQuality: FilterQuality.high,
        ),
        const DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Color(0xC808101C),
                Color(0x850A1420),
                Color(0xC908101A),
                Color(0xF4080B13),
              ],
              stops: [0.0, 0.3, 0.66, 1.0],
            ),
          ),
        ),
      ],
    ),
  );
}
