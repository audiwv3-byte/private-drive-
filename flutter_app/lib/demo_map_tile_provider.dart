import 'package:flutter_map/flutter_map.dart';

/// Isolated Android demo workaround for flutter_map 8.3.x's native file cache.
///
/// The default BuiltInMapCachingProvider reaches path_provider_android through
/// JNI and throws ClassNotFoundException on the current test Android runtime,
/// preventing all tiles from rendering. The demo uses Flutter's in-memory image
/// cache only. Before production, replace with a compatible persistent cache
/// and a licensed tile provider; do not use this for high-volume public OSM.
class DemoDisabledTileCache with DisabledMapCachingProvider
    implements MapCachingProvider {}

// Reuse one network provider across Flutter rebuilds. Constructing a new
// provider from every TileLayer build can replace in-flight image requests
// while GPS, network state and other map UI elements update.
final NetworkTileProvider _demoNetworkTiles = NetworkTileProvider(
  cachingProvider: DemoDisabledTileCache(),
);

NetworkTileProvider demoTileProvider() => _demoNetworkTiles;
