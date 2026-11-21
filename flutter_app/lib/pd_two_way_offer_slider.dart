import 'package:flutter/material.dart';

/// One deliberate control for both directions; releasing early cancels.
/// Right: accept, left: decline. No network or payment side effects.
class PdTwoWayOfferSlider extends StatefulWidget {
  const PdTwoWayOfferSlider({
    super.key,
    required this.onAccept,
    required this.onDecline,
    this.enabled = true,
    this.acceptKey,
    this.handleKey,
    this.declineKey,
  });

  final VoidCallback onAccept;
  final VoidCallback onDecline;
  final bool enabled;
  final Key? acceptKey;
  final Key? handleKey;
  final Key? declineKey;

  @override
  State<PdTwoWayOfferSlider> createState() => _PdTwoWayOfferSliderState();
}

class _PdTwoWayOfferSliderState extends State<PdTwoWayOfferSlider> {
  static const double thumbSize = 54;
  static const Color gold = Color(0xFFDDC184);
  double _drag = 0;
  bool _completed = false;

  @override
  void didUpdateWidget(PdTwoWayOfferSlider oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled && oldWidget.enabled) {
      _drag = 0;
      _completed = false;
    } else if (widget.enabled && !oldWidget.enabled) {
      _completed = false;
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final halfTravel = ((constraints.maxWidth - thumbSize) / 2)
          .clamp(0.0, 5000.0);
      return Container(
        height: 58,
        decoration: BoxDecoration(
          color: const Color(0xFF22272D),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: const Color(0x886E5934)),
        ),
        child: Stack(
          alignment: Alignment.center,
          children: [
            Positioned(
              left: 9,
              child: Row(
                key: widget.declineKey,
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Icon(Icons.chevron_left, color: Color(0xFFFF8282)),
                  Text('Отказаться',
                    style: TextStyle(color: Color(0xFFFFB4B4), fontSize: 12)),
                ],
              ),
            ),
            Positioned(
              right: 9,
              child: Row(
                key: widget.acceptKey,
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Text('Принять', style: TextStyle(color: gold, fontSize: 12)),
                  Icon(Icons.chevron_right, color: gold),
                ],
              ),
            ),
            AnimatedPositioned(
              duration: const Duration(milliseconds: 100),
              curve: Curves.easeOut,
              left: halfTravel + _drag.clamp(-halfTravel, halfTravel),
              top: 1,
              child: GestureDetector(
                key: widget.handleKey,
                behavior: HitTestBehavior.opaque,
                onHorizontalDragStart: widget.enabled && !_completed
                    ? (_) => setState(() => _drag = 0) : null,
                onHorizontalDragUpdate: widget.enabled && !_completed
                    ? (details) => setState(() {
                        _drag = (_drag + details.delta.dx)
                            .clamp(-halfTravel, halfTravel);
                      }) : null,
                onHorizontalDragEnd: widget.enabled && !_completed
                    ? (_) {
                        final accept = halfTravel > 20 &&
                            _drag >= halfTravel * 0.88;
                        final decline = halfTravel > 20 &&
                            _drag <= -halfTravel * 0.88;
                        setState(() {
                          _drag = 0;
                          _completed = accept || decline;
                        });
                        if (accept) widget.onAccept();
                        if (decline) widget.onDecline();
                      } : null,
                onHorizontalDragCancel: () => setState(() => _drag = 0),
                child: Container(
                  width: thumbSize,
                  height: 54,
                  decoration: BoxDecoration(
                    color: widget.enabled ? gold : Colors.grey,
                    borderRadius: BorderRadius.circular(16),
                    boxShadow: const [
                      BoxShadow(color: Colors.black45, blurRadius: 6),
                    ],
                  ),
                  child: const Icon(Icons.directions_car_filled_outlined,
                    color: Color(0xFF131820), size: 30),
                ),
              ),
            ),
          ],
        ),
      );
    },
  );
}
