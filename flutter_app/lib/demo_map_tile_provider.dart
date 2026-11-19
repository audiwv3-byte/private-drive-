import 'package:flutter/painting.dart';
import 'package:flutter_map/flutter_map.dart';

/// Isolated Android demo raster provider.
///
/// flutter_map's default NetworkTileProvider returned HTTP 400 for valid
/// public tiles on the test Android runtime, while dart:io HttpClient with this
/// explicit User-Agent fetched the same OSM PNG as HTTP 200. Use Flutter's
/// direct NetworkImage transport and its short-lived in-memory ImageCache.
///
/// Never use this uncached public OSM setup for a high-volume production fleet.
/// Production needs a licensed provider and compatible persistent caching.
class DemoDirectNetworkTileProvider extends TileProvider {
  DemoDirectNetworkTileProvider()
      : super(headers: <String, String>{
          'User-Agent': 'PRIVATE DRIVE demo Android visual QA',
          'Accept': 'image/png,image/*',
        });

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) {
    return NetworkImage(getTileUrl(coordinates, options), headers: headers);
  }
}

TileProvider demoTileProvider() => DemoDirectNetworkTileProvider();
