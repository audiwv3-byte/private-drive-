import 'package:flutter/material.dart';
import 'pilot_identity_notice_page.dart';

/// Standalone entry point for the separately packaged Android camera test APK.
///
/// Does not initialize native sign-in, orders, dispatcher privileges, network
/// sync, a real pilot account, camera capture or biometrics. Never use this
/// entry point for a release or production package.
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const PdIsolatedCameraTestApp());
}

class PdIsolatedCameraTestApp extends StatelessWidget {
  const PdIsolatedCameraTestApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PD CAMERA TEST',
      debugShowCheckedModeBanner: true,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFB99954),
          brightness: Brightness.dark,
        ),
      ),
      home: const PdIsolatedPilotCameraHome(),
    );
  }
}

class PdIsolatedPilotCameraHome extends StatelessWidget {
  const PdIsolatedPilotCameraHome({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: const Key('isolated-camera-pilot-home'),
      appBar: AppBar(title: const Text('PD CAMERA TEST · Пилот')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Icon(Icons.verified_user_outlined,
                size: 72, color: Color(0xFFDDC184)),
            const SizedBox(height: 16),
            const Text('Тест проверки личности пилота',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            const Text(
              'Изолированный тест без входа по телефону. '
              'Это не рабочая кабина пилота: поездки, заказы, '
              'права администратора и серверная авторизация недоступны. '
              'Снимки не создаются и не отправляются.',
              key: Key('isolated-camera-safety-explanation'),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              key: const Key('isolated-camera-open-identity'),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const PdPilotIdentityNoticePage(),
                ),
              ),
              icon: const Icon(Icons.camera_alt_outlined),
              label: const Text('Проверка личности · раз в 7 дней'),
            ),
          ],
        ),
      ),
    );
  }
}
