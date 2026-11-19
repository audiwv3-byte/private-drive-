import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
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

  Future<void> verifyEmulatorNetwork(WidgetTester tester, String role) async {
    await tester.runAsync(() async {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 8);
      try {
        final uri = Uri.parse(
            'https://tile.openstreetmap.org/10/583/325.png');
        final request = await client.getUrl(uri)
            .timeout(const Duration(seconds: 10));
        request.headers.set(HttpHeaders.userAgentHeader,
            'PRIVATE DRIVE demo Android visual QA');
        final response = await request.close()
            .timeout(const Duration(seconds: 10));
        final chunks = await response.toList()
            .timeout(const Duration(seconds: 10));
        final raw = Uint8List.fromList(chunks.expand((part) => part).toList());
        // This checks the emulator, not just the GitHub runner.
        // Keep the result explicit in CI logs.
        // ignore: avoid_print
        print('EMULATOR_MAP_HTTP_$role: status=${response.statusCode} '
            'type=${response.headers.contentType} bytes=${raw.length}');
        expect(response.statusCode, HttpStatus.ok,
            reason: 'Android emulator itself cannot load OSM tile');
        expect(raw.length, greaterThan(8));
        expect(raw[0], 0x89, reason: 'Not a PNG tile');
        expect(raw[1], 0x50, reason: 'Not a PNG tile');
        final codec = await ui.instantiateImageCodec(raw);
        try {
          final frame = await codec.getNextFrame();
          try {
            // ignore: avoid_print
            print('EMULATOR_MAP_DECODE_$role: '
                '${frame.image.width}x${frame.image.height}');
            expect(frame.image.width, 256);
            expect(frame.image.height, 256);
          } finally {
            frame.image.dispose();
          }
        } finally {
          codec.dispose();
        }
      } finally {
        client.close(force: true);
      }
    });
  }

  Future<Set<int>> sampleCleanMapArea(
      WidgetTester tester, GlobalKey frameKey, Rect mapRect,
      {required double xStart, required double xEnd,
       required double yStart, required double yEnd}) async {
    final boundary = frameKey.currentContext!.findRenderObject()
        as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: 1);
    // ignore: avoid_print
    print('MAP_RENDER_SAMPLE: surface=${image.width}x${image.height} '
        'mapRect=$mapRect');
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

  testWidgets('Pixel reader detects a known multicolor Android gradient',
      (tester) async {
    final key = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(
      key: key,
      child: const MaterialApp(home: Scaffold(
        body: DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [Colors.red, Colors.blue],
            ),
          ),
          child: SizedBox.expand(),
        ),
      )),
    ));
    await tester.pump();
    final rect = tester.getRect(find.byType(Scaffold));
    final palette = await sampleCleanMapArea(tester, key, rect,
        xStart: 0.15, xEnd: 0.85, yStart: 0.15, yEnd: 0.85);
    // ignore: avoid_print
    print('PIXEL_READER_CALIBRATION: colors=${palette.length}');
    expect(palette.length, greaterThan(20),
      reason: 'Android screenshot reader cannot capture known gradient');
  });

  Future<void> flushRasterImageFrames(WidgetTester tester) async {
    // Real HTTP fetch and image decoding happen outside the widget-test fake
    // clock. Pump successive frames to allow completed images to be painted.
    // This does not weaken the independent pixel-colour assertion below.
    for (var i = 0; i < 12; i++) {
      await tester.runAsync(() => Future<void>.delayed(
          const Duration(milliseconds: 250)));
      await tester.pump(const Duration(milliseconds: 150));
    }
  }

  testWidgets('Passenger raster streets visibly painted on real Android',
      (tester) async {
    final key = GlobalKey();
    await verifyEmulatorNetwork(tester, 'PASSENGER');
    await tester.pumpWidget(RepaintBoundary(
      key: key,
      child: const MaterialApp(
        home: PassengerDemo(enableMapTiles: true),
      ),
    ));
    await tester.runAsync(() => Future<void>.delayed(
      const Duration(seconds: 18)));

    await flushRasterImageFrames(tester);
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
    // Night uses the same reachable OSM raster under a local dark filter.
    await tester.tap(find.byKey(const Key('passenger-map-day-night')));
    await flushRasterImageFrames(tester);
    expect(find.byKey(const Key('passenger-map-load-error')), findsNothing);
    final nightPalette = await sampleCleanMapArea(tester, key, mapRect,
      xStart: 0.08, xEnd: 0.48, yStart: 0.12, yEnd: 0.38);
    expect(nightPalette.length, greaterThan(20),
      reason: 'Passenger night raster is blank');
  });

  testWidgets('Pilot raster streets visibly painted on real Android',
      (tester) async {
    final key = GlobalKey();
    await verifyEmulatorNetwork(tester, 'PILOT');
    await tester.pumpWidget(RepaintBoundary(
      key: key,
      child: const MaterialApp(
        home: PilotDemo(enableMapTiles: true, loadMapTiles: true),
      ),
    ));
    await tester.runAsync(() => Future<void>.delayed(
      const Duration(seconds: 18)));

    // Match the passenger raster test: pump frames after asynchronous HTTP/
    // image decoding. A single 300 ms pump can capture the unpainted map.
    await flushRasterImageFrames(tester);
    expect(find.byKey(const Key('pilot-map-load-error')), findsNothing,
      reason: 'Pilot map detected failed network tile requests');
    final rect = tester.getRect(find.byKey(const Key('pilot-map-surface')));
    final palette = await sampleCleanMapArea(tester, key, rect,
      xStart: 0.55, xEnd: 0.90, yStart: 0.23, yEnd: 0.48);
    expect(palette.length, greaterThan(20),
      reason: 'Pilot tile region has only ${palette.length} colors '
              '(blank raster background; map is NOT ready)');
    await tester.tap(find.byKey(const Key('pilot-map-day-night')));
    await flushRasterImageFrames(tester);
    expect(find.byKey(const Key('pilot-map-load-error')), findsNothing);
    final nightPalette = await sampleCleanMapArea(tester, key, rect,
      xStart: 0.55, xEnd: 0.90, yStart: 0.23, yEnd: 0.48);
    expect(nightPalette.length, greaterThan(20),
      reason: 'Pilot night raster is blank');
  });
}
