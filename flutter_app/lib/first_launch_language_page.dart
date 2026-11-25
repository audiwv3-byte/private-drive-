import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'app_language.dart';
import 'brand_logo.dart';
import 'company_info.dart';
import 'private_drive_bright_backdrop.dart';

class PdFirstLaunchLanguage extends StatefulWidget {
  const PdFirstLaunchLanguage({super.key, required this.child});

  final Widget child;

  @override
  State<PdFirstLaunchLanguage> createState() => _PdFirstLaunchLanguageState();
}

class _PdFirstLaunchLanguageState extends State<PdFirstLaunchLanguage> {
  bool _acknowledged = false;
  bool _saving = false;

  @override
  Widget build(BuildContext context) {
    final language = PdLanguageScope.of(context);
    if (language.hasSelection && language.hasAcknowledgedTerms) {
      return widget.child;
    }

    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [
          const PrivateDriveBrightBackdrop(),
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 440),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const _FirstLaunchLogo(),
                      const SizedBox(height: 24),
                      Wrap(
                        alignment: WrapAlignment.center,
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          for (final (code, flag, name) in const [
                            ('RU', '🇷🇺', 'Русский'),
                            ('EN', '🇬🇧', 'English'),
                            ('LT', '🇱🇹', 'Lietuvių'),
                          ])
                            OutlinedButton(
                              key: ValueKey('first-language-$code'),
                              onPressed: _saving
                                  ? null
                                  : () {
                                      if (language.value != code) {
                                        setState(() => _acknowledged = false);
                                      }
                                      language.set(code);
                                    },
                              style: OutlinedButton.styleFrom(
                                backgroundColor: const Color(0xED111111),
                                side:
                                    language.hasSelection &&
                                        language.value == code
                                    ? BorderSide(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .primary,
                                      )
                                    : null,
                              ),
                              child: Text('$flag $code', semanticsLabel: name),
                            ),
                        ],
                      ),
                      if (language.hasSelection) ...[
                        const SizedBox(height: 16),
                        Card(
                          color: const Color(0xF5111111),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                TextButton.icon(
                                  onPressed: _saving
                                      ? null
                                      : () => Navigator.of(context).push(
                                          MaterialPageRoute<void>(
                                            builder: (_) =>
                                                const CompanyInfoPage(
                                                  initialTab: 1,
                                                ),
                                          ),
                                        ),
                                  icon: const Icon(Icons.gavel_outlined),
                                  label: Text(
                                    pdEntryTr(
                                      context,
                                      'Условия сервиса и политика конфиденциальности',
                                      'Paslaugos sąlygos ir privatumo politika',
                                      'Terms of service and privacy policy',
                                    ),
                                  ),
                                ),
                                CheckboxListTile(
                                  key: const Key(
                                    'first-launch-terms-acknowledgement',
                                  ),
                                  contentPadding: EdgeInsets.zero,
                                  controlAffinity:
                                      ListTileControlAffinity.leading,
                                  value: _acknowledged,
                                  onChanged: _saving
                                      ? null
                                      : (value) => setState(
                                          () => _acknowledged = value ?? false,
                                        ),
                                  title: Text(
                                    pdEntryTr(
                                      context,
                                      'Я ознакомился с условиями сервиса и политикой конфиденциальности',
                                      'Susipažinau su paslaugos sąlygomis ir privatumo politika',
                                      'I have read the terms of service and privacy policy',
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 8),
                                FilledButton(
                                  key: const Key('first-launch-continue'),
                                  onPressed: !_acknowledged || _saving
                                      ? null
                                      : () async {
                                          setState(() => _saving = true);
                                          await language.acknowledgeTerms();
                                        },
                                  child: Text(
                                    pdEntryTr(
                                      context,
                                      'Продолжить',
                                      'Tęsti',
                                      'Continue',
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _FirstLaunchLogo extends StatefulWidget {
  const _FirstLaunchLogo();

  @override
  State<_FirstLaunchLogo> createState() => _FirstLaunchLogoState();
}

class _FirstLaunchLogoState extends State<_FirstLaunchLogo>
    with SingleTickerProviderStateMixin {
  late final _lights = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2400),
  );
  bool _animated = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _lights.stop();
      _lights.value = 1;
    } else if (!_animated) {
      _animated = true;
      _lights.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _lights.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(
    children: [
      const PrivateDriveBrandLogo(size: 260, transparentBackground: true),
      Positioned.fill(
        child: IgnorePointer(
          child: CustomPaint(painter: _HeadlightGlow(_lights)),
        ),
      ),
    ],
  );
}

class _HeadlightGlow extends CustomPainter {
  _HeadlightGlow(this.animation) : super(repaint: animation);

  final Animation<double> animation;

  @override
  void paint(Canvas canvas, Size size) {
    if (animation.isCompleted || animation.isDismissed) return;
    final pulse = animation.value * 4;
    final intensity = math.sin(math.pi * (pulse % 1));
    // Headlight centres in the approved 512×512 square asset.
    final x = pulse.floor().isEven ? 166 / 512 : 325 / 512;
    final centre = Offset(size.width * x, size.height * (409 / 512));
    final radius = size.shortestSide * 0.062;
    canvas.drawCircle(
      centre,
      radius,
      Paint()
        ..shader = RadialGradient(
          colors: [
            const Color(0xFFFFF4CD).withValues(alpha: intensity * 0.52),
            const Color(0x00FFD27E),
          ],
        ).createShader(Rect.fromCircle(center: centre, radius: radius)),
    );
  }

  @override
  bool shouldRepaint(covariant _HeadlightGlow oldDelegate) =>
      oldDelegate.animation != animation;
}
