import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:private_drive/demo_interfaces.dart';
import 'package:private_drive/passenger_demo.dart';

/// Actual Android rendering smoke test; NOT a widget-only or mocked HTTP test.
/// Runs on an Android emulator with real raster tile requests, then reads the
/// painted frame. A solid/blank map fails even if FlutterMap exists in the tree.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  Future<Set<int>> sampleCleanMapArea(
      WidgetTester tester, GlobalKey frameKey, Rect mapRect,
      {required double xStart, required double xEnd,
       required double yStart, required double yEnd}) async {
    final boundary = frameKey.currentContext!.findRenderObject()
        as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: 1);
    try {
      final bytes = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      if (bytes == null) throw StateError('Screenshot pixel data unavailable');
      final raw = bytes.buffer.asUint8List();
      final colors = <int>{};
      for (var iy = 0; iy < 25; iy++) {
        for (var ix = 0; ix < 25; ix++) {
          final fx = xStart + (xEnd - xStart) * ix / 24;
          final fy = yStart + (yEnd - yStart) * iy / 24;
          final x = (mapRect.left + mapRect.width * fx).round()
              .clamp(0, image.width - 1);
          final y = (mapRect.top + mapRect.height * fy).round()
              .clamp(0, image.height - 1);
          final offset = (y * image.width + x) * 4;
          // Quantize slightly so anti-aliasing around text cannot yield a pass.
          final red = raw[offset] >> 3;
          final green = raw[offset + 1] >> 3;
          final blue = raw[offset + 2] >> 3;
          colors.add((red << 10) | (green << 5) | blue);
        }
      }
      return colors;
    } finally {
      image.dispose();
    }
  }

  testWidgets('Passenger raster streets visibly painted on real Android',
      (tester) async {
    final key = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(
      key: key,
      child: const MaterialApp(
        home: PassengerDemo(enableMapTiles: true),
      ),
    ));
    await tester.runAsync(() => Future<void>.delayed(
      const Duration(seconds: 18)));

    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('passenger-map')), findsOneWidget);
    expect(find.byKey(const Key('passenger-map-load-error')), findsNothing,
        reason: 'Passenger map detected a tile or HTTPS error');
    final mapRect = tester.getRect(find.byKey(const Key('passenger-map')));
    final palette = await sampleCleanMapArea(tester, key, mapRect,
      xStart: 0.08, xEnd: 0.48, yStart: 0.12, yEnd: 0.38);
    // Flat black/white/blue background has roughly one quantized color.
    // Real street tiles contain roads, labels, buildings, and boundaries.
    expect(palette.length, greaterThan(20),
      reason: 'Passenger tile region has only ${palette.length} colors '
              '(blank raster background; map is NOT ready)');
  });

  testWidgets('Pilot raster streets visibly painted on real Android',
      (tester) async {
    final key = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(
      key: key,
      child: const MaterialApp(
        home: PilotDemo(enableMapTiles: true, loadMapTiles: true),
      ),
    ));
    await tester.runAsync(() => Future<void>.delayed(
      const Duration(seconds: 18)));

    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('pilot-map-load-error')), findsNothing,
      reason: 'Pilot map detected failed network tile requests');
    final rect = tester.getRect(find.byKey(const Key('pilot-map-surface')));
    final palette = await sampleCleanMapArea(tester, key, rect,
      xStart: 0.55, xEnd: 0.90, yStart: 0.23, yEnd: 0.48);
    expect(palette.length, greaterThan(20),
      reason: 'Pilot tile region has only ${palette.length} colors '
              '(blank raster background; map is NOT ready)');
  });
}
