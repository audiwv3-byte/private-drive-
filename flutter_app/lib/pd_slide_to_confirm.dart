import 'package:flutter/material.dart';

/// A deliberate slide-to-confirm control: the thumb must travel almost all
/// the way from left to right. A tap or a short swipe never confirms.
class PdSlideToConfirm extends StatefulWidget {
  const PdSlideToConfirm({
    super.key,
    required this.label,
    required this.onConfirmed,
    this.enabled = true,
    this.thumbKey,
    this.color = const Color(0xFF126B40),
  });

  final String label;
  final VoidCallback onConfirmed;
  final bool enabled;
  final Key? thumbKey;
  final Color color;

  @override
  State<PdSlideToConfirm> createState() => _PdSlideToConfirmState();
}

class _PdSlideToConfirmState extends State<PdSlideToConfirm> {
  static const double thumbSize = 52;
  double _drag = 0;

  @override
  void didUpdateWidget(PdSlideToConfirm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled && oldWidget.enabled) _drag = 0;
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final length = (constraints.maxWidth - thumbSize).clamp(0.0, 10000.0);
      final distance = _drag.clamp(0.0, length);
      return Container(
        height: 54,
        decoration: BoxDecoration(
          color: widget.enabled ? widget.color : const Color(0xFF414141),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.white24),
        ),
        child: Stack(
          alignment: Alignment.centerLeft,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 60, right: 8),
              child: Center(child: Text(
                widget.label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Colors.white, fontWeight: FontWeight.w700),
              )),
            ),
            AnimatedPositioned(
              duration: const Duration(milliseconds: 85),
              curve: Curves.easeOut,
              left: distance,
              top: 1,
              child: GestureDetector(
                key: widget.thumbKey,
                behavior: HitTestBehavior.opaque,
                onHorizontalDragStart: widget.enabled
                    ? (_) => setState(() => _drag = 0) : null,
                onHorizontalDragUpdate: widget.enabled
                    ? (details) => setState(() {
                        _drag = (_drag + details.delta.dx).clamp(0.0, length);
                      }) : null,
                onHorizontalDragEnd: widget.enabled ? (_) {
                  final complete = length > 20 && _drag >= length * 0.94;
                  setState(() => _drag = 0);
                  if (complete) widget.onConfirmed();
                } : null,
                onHorizontalDragCancel: () => setState(() => _drag = 0),
                child: Container(
                  width: thumbSize, height: 50,
                  decoration: BoxDecoration(
                    color: widget.enabled
                        ? const Color(0xFFB6FF36) : Colors.white38,
                    borderRadius: BorderRadius.circular(14),
                    boxShadow: const [BoxShadow(
                      color: Colors.black54, blurRadius: 5)],
                  ),
                  child: const Icon(Icons.double_arrow_rounded,
                    color: Color(0xFF172B3F), size: 32),
                ),
              ),
            ),
          ],
        ),
      );
    },
  );
}
