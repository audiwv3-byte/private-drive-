/// Isolated Mapbox QA configuration for PRIVATE DRIVE.
///
/// Supply MAPBOX_PUBLIC_TOKEN through --dart-define in the QA workflow.
/// Never commit tokens or use this config for production automatically.
/// Mapbox raster tiles are compatible with flutter_map. Native 3D buildings
/// and camera navigation require a separate Mapbox Maps SDK integration.
class PdMapboxQaConfig {
  static const publicToken = String.fromEnvironment('MAPBOX_PUBLIC_TOKEN');
  static const enabled = bool.fromEnvironment('PD_MAPBOX_QA', defaultValue: false);
  static const styleId = 'dark-v11';

  static bool get hasPublicToken => publicToken.startsWith('pk.');
  static bool get canUseMapbox => enabled && hasPublicToken;

  static String? get rasterTileUrl {
    if (!canUseMapbox) return null;
    return 'https://api.mapbox.com/styles/v1/mapbox/$styleId/tiles/256/'
        '{z}/{x}/{y}?access_token=$publicToken';
  }

  static const attribution = '© Mapbox © OpenStreetMap';
}
