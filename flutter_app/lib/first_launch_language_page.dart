import 'package:flutter/material.dart';

import 'app_language.dart';
import 'brand_logo.dart';
import 'private_drive_bright_backdrop.dart';

class PdFirstLaunchLanguage extends StatelessWidget {
  const PdFirstLaunchLanguage({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final language = PdLanguageScope.of(context);
    if (language.hasSelection) return child;

    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [
          const PrivateDriveBrightBackdrop(),
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const PrivateDriveBrandLogo(size: 260, circular: true),
                    const SizedBox(height: 32),
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
                            onPressed: () => language.set(code),
                            style: OutlinedButton.styleFrom(
                              backgroundColor: const Color(0xED111111),
                            ),
                            child: Text('$flag $code', semanticsLabel: name),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
