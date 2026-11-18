import 'package:flutter/material.dart';

/// Decorative offline-only Vilnius evening skyline. No GPS, network or map tiles.
class VilniusEveningBackdrop extends StatelessWidget {
  const VilniusEveningBackdrop({super.key});

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: Opacity(
      opacity: 0.44,
      child: CustomPaint(
        key: const Key('pilot-offline-vilnius-background'),
        painter: _VilniusSkylinePainter(),
        child: const SizedBox.expand(),
      ),
    ),
  );
}

class _VilniusSkylinePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final sky = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          Color(0xFF081023), Color(0xFF293655),
          Color(0xFF845B55), Color(0xFF171923),
        ],
        stops: [0.0, 0.36, 0.76, 1.0],
      ).createShader(Offset.zero & size);
    canvas.drawRect(Offset.zero & size, sky);

    // Soft distant city glow, kept behind all buttons and labels.
    canvas.drawCircle(Offset(w * .54, h * .68), w * .45,
      Paint()..color = const Color(0xFFD99D64).withValues(alpha: .11)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 45));

    void block(double x, double top, double width, double bottom,
        Color color) => canvas.drawRect(
          Rect.fromLTRB(w * x, h * top, w * (x + width), h * bottom),
          Paint()..color = color);

    const far = Color(0xFF20293A);
    const near = Color(0xFF101725);
    // Vilnius Old Town's irregular historic roofline.
    for (final b in <List<double>>[
      [.00,.67,.095,.88], [.075,.63,.11,.88], [.18,.69,.09,.88],
      [.27,.61,.12,.88], [.39,.66,.10,.88], [.49,.62,.13,.88],
      [.62,.68,.10,.88], [.71,.59,.12,.88], [.82,.65,.10,.88],
      [.90,.61,.10,.88],
    ]) {
      block(b[0], b[1], b[2], b[3], far);
    }

    // Hill of Gediminas with recognizable square tower.
    final hill = Path()
      ..moveTo(w * .04, h * .83)
      ..quadraticBezierTo(w * .19, h * .66, w * .34, h * .78)
      ..lineTo(w * .4, h * .88)
      ..close();
    canvas.drawPath(hill, Paint()..color = near);
    block(.205, .58, .065, .72, const Color(0xFF1B2231));
    block(.197, .569, .081, .587, const Color(0xFF1B2231));
    for (final x in [.211, .232, .253]) {
      block(x, .551, .014, .578, const Color(0xFF1B2231));
    }

    // Church spires and domes echo the Vilnius skyline.
    void spire(double x, double y, double width, double height) {
      block(x, y, width, height, near);
      final roof = Path()
        ..moveTo(w * (x - width * .22), h * y)
        ..lineTo(w * (x + width * .5), h * (y - .115))
        ..lineTo(w * (x + width * 1.22), h * y)
        ..close();
      canvas.drawPath(roof, Paint()..color = near);
    }
    spire(.445, .61, .045, .84);
    spire(.515, .57, .032, .84);
    spire(.745, .60, .046, .85);

    // Cathedral-inspired classical front and bell tower.
    block(.58, .69, .145, .87, near);
    final pediment = Path()
      ..moveTo(w * .565, h * .69)
      ..lineTo(w * .652, h * .645)
      ..lineTo(w * .74, h * .69)
      ..close();
    canvas.drawPath(pediment, Paint()..color = near);
    for (final x in [.595, .625, .655, .685]) {
      block(x, .71, .012, .83, const Color(0xFF404050));
    }
    block(.84, .55, .045, .86, near);
    block(.836, .54, .053, .553, near);

    // Warm windows with a sparse, non-repeating rhythm.
    final window = Paint()..color = const Color(0xFFDFA46A).withValues(alpha: .52);
    for (var i = 0; i < 23; i++) {
      final x = (i * 37 % 97) / 100;
      final y = .75 + (i % 4) * .026;
      canvas.drawRect(Rect.fromLTWH(w * x, h * y, w * .006, h * .008), window);
    }

    // Dark foreground makes POWER and white captions easy to read.
    canvas.drawRect(Rect.fromLTRB(0, h * .85, w, h),
      Paint()..color = const Color(0xFF080D17));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
