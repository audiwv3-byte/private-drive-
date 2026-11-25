import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Isolated Mapbox QA configuration for PRIVATE DRIVE.
///
/// Supply MAPBOX_PUBLIC_TOKEN through --dart-define in the QA workflow.
/// Never commit tokens or use this config for production automatically.
/// Mapbox raster tiles are compatible with flutter_map. Native 3D buildings
/// and camera navigation require a separate Mapbox Maps SDK integration.
class PdMapboxQaConfig {
  static const publicToken = String.fromEnvironment('MAPBOX_PUBLIC_TOKEN');
  static const enabled = bool.fromEnvironment('PD_MAPBOX_QA', defaultValue: false);

  static bool get hasPublicToken => publicToken.startsWith('pk.');
  static bool get canUseMapbox => enabled && hasPublicToken;

  static String? rasterTileUrl({required bool night}) {
    if (!canUseMapbox) return null;
    final styleId = night ? 'dark-v11' : 'light-v11';
    return 'https://api.mapbox.com/styles/v1/mapbox/$styleId/tiles/256/'
        '{z}/{x}/{y}?access_token=$publicToken';
  }
}

class PdMapboxAttribution extends StatelessWidget {
  const PdMapboxAttribution({super.key});

  @override
  Widget build(BuildContext context) => Align(
    alignment: Alignment.topCenter,
    child: Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Material(
        color: const Color(0xED151515),
        borderRadius: BorderRadius.circular(8),
        child: PopupMenuButton<String>(
          tooltip: 'Mapbox · © OpenStreetMap',
          onSelected: (url) => launchUrl(Uri.parse(url),
              mode: LaunchMode.externalApplication),
          itemBuilder: (_) => const [
            PopupMenuItem(
              value: 'https://www.mapbox.com/about/maps/',
              child: Text('© Mapbox'),
            ),
            PopupMenuItem(
              value: 'https://www.openstreetmap.org/copyright',
              child: Text('© OpenStreetMap'),
            ),
            PopupMenuItem(
              value: 'https://apps.mapbox.com/feedback/',
              child: Text('Improve this map'),
            ),
          ],
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
            child: const Text('© Mapbox', style: TextStyle(
              color: Color(0xFFDDC184), fontSize: 12, fontWeight: FontWeight.w600)),
          ),
        ),
      ),
    ),
  );
}

class PdPilotMapMarker extends StatelessWidget {
  const PdPilotMapMarker({super.key});

  @override
  Widget build(BuildContext context) => Container(
    alignment: Alignment.center,
    decoration: BoxDecoration(
      color: const Color(0xFF17130C),
      shape: BoxShape.circle,
      border: Border.all(color: const Color(0xFFE5C57B), width: 2.5),
      boxShadow: const [BoxShadow(color: Colors.black54, blurRadius: 7)],
    ),
    child: const Text('PD', style: TextStyle(
      color: Color(0xFFE5C57B), fontSize: 16, fontWeight: FontWeight.w900,
    )),
  );
}
