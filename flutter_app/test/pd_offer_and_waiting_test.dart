import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_drive/pd_two_way_offer_slider.dart';
import 'package:private_drive/pd_pilot_assignment_waiting.dart';

void main() {
  Future<void> mountSlider(WidgetTester tester, {
    required VoidCallback accept,
    required VoidCallback decline,
  }) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Center(child: SizedBox(
          width: 330,
          child: PdTwoWayOfferSlider(
            key: const Key('two-way-control'),
            handleKey: const Key('two-way-handle'),
            onAccept: accept,
            onDecline: decline,
          ),
        )),
      ),
    ));
  }

  testWidgets('right swipe accepts once', (tester) async {
    var accepted = 0;
    var declined = 0;
    await mountSlider(tester,
      accept: () => accepted++,
      decline: () => declined++);
    await tester.drag(find.byKey(const Key('two-way-handle')),
      const Offset(140, 0));
    await tester.pump();
    expect(accepted, 1);
    expect(declined, 0);
  });

  testWidgets('left swipe declines once', (tester) async {
    var accepted = 0;
    var declined = 0;
    await mountSlider(tester,
      accept: () => accepted++,
      decline: () => declined++);
    await tester.drag(find.byKey(const Key('two-way-handle')),
      const Offset(-140, 0));
    await tester.pump();
    expect(accepted, 0);
    expect(declined, 1);
  });

  testWidgets('short swipe does not accept or decline', (tester) async {
    var accepted = 0;
    var declined = 0;
    await mountSlider(tester,
      accept: () => accepted++,
      decline: () => declined++);
    await tester.drag(find.byKey(const Key('two-way-handle')),
      const Offset(25, 0));
    await tester.pump();
    expect(accepted, 0);
    expect(declined, 0);
  });

  testWidgets('branded waiting indicator is non-financial',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: PdPilotAssignmentWaiting())),
    ));
    expect(find.byKey(const Key('passenger-pd-waiting-indicator')),
      findsOneWidget);
    expect(find.text('Ожидаем назначения пилота'), findsOneWidget);
    expect(find.textContaining('тестовый режим'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
