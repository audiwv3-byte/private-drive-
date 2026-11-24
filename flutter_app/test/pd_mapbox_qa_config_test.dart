import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pd_mapbox_qa_config.dart';

void main() {
  const expectMapbox = bool.fromEnvironment('PD_EXPECT_MAPBOX');

  test('selects Mapbox only for enabled QA with a public token', () {
    expect(PdMapboxQaConfig.canUseMapbox, expectMapbox);

    final tileUrl = PdMapboxQaConfig.rasterTileUrl;
    if (!expectMapbox) {
      expect(tileUrl, isNull);
      return;
    }

    expect(
      tileUrl,
      'https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/256/'
      '{z}/{x}/{y}?access_token=pk.qa_fixture',
    );
  });
}
