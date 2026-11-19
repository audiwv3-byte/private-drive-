import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'demo_interfaces.dart';
import 'brand_logo.dart';
import 'app_language.dart';

const apiBaseUrl = String.fromEnvironment('PD_NATIVE_AUTH_API_URL');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await pdLanguage.restore();
  runApp(const PrivateDriveApp());
}

class PrivateDriveApp extends StatelessWidget {
  const PrivateDriveApp({super.key});

  @override
  Widget build(BuildContext context) {
    return PdLanguageScope(
      language: pdLanguage,
      child: MaterialApp(
      title: 'PRIVATE DRIVE',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFB99954),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF111111),
      ),
      home: const NativeSignInScreen(),
      ),
    );
  }
}

class NativeSignInScreen extends StatefulWidget {
  const NativeSignInScreen({super.key});

  @override
  State<NativeSignInScreen> createState() => _NativeSignInScreenState();
}

class _NativeSignInScreenState extends State<NativeSignInScreen> {
  final destination = TextEditingController();
  final code = TextEditingController();
  bool busy = false;
  String get language => PdLanguageScope.of(context).value;

  String tr(String ru, String lt, String en) =>
      language == 'LT' ? lt : language == 'EN' ? en : ru;

  Widget languageSwitcher() => Row(
    key: const Key('native-language-switcher'),
    mainAxisAlignment: MainAxisAlignment.end,
    children: [
      for (final entry in const [['RU', '🇷🇺'], ['LT', '🇱🇹'], ['EN', '🇬🇧']])
        Padding(
          padding: const EdgeInsets.only(left: 4),
          child: ChoiceChip(
            key: Key('native-language-${entry[0]}'),
            label: Text('${entry[1]} ${entry[0]}'),
            selected: language == entry[0],
            onSelected: (_) => pdLanguage.set(entry[0]),
          ),
        ),
    ],
  );
  String? challengeId;
  String message = '';
  String? sessionToken;
  String? signedInUserId;
  DateTime? sessionExpiry;

  @override
  void dispose() {
    destination.dispose();
    code.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> post(String path, Map<String, String> payload) async {
    final base = Uri.tryParse(apiBaseUrl);
    if (base == null || base.scheme != 'https' || base.host.isEmpty) {
      throw const FormatException('Безопасный адрес API не настроен.');
    }
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final request = await client.postUrl(base.resolve(path))
          .timeout(const Duration(seconds: 10));
      request.headers.contentType = ContentType.json;
      request.add(utf8.encode(jsonEncode(payload)));
      final response = await request.close().timeout(const Duration(seconds: 10));
      final body = await utf8.decoder.bind(response).join();
      final decoded = jsonDecode(body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Некорректный ответ сервера.');
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('Запрос отклонён (HTTP ${response.statusCode}).');
      }
      return decoded;
    } finally {
      client.close(force: true);
    }
  }

  Future<void> requestCode() async {
    if (busy) return;
    setState(() {
      busy = true;
      message = '';
    });
    try {
      final result = await post('/native-auth/request-code', {
        'channel': 'phone',
        'destination': destination.text.trim(),
      });
      final id = result['challenge_id'];
      if (id is! String || id.isEmpty) {
        throw const FormatException('Сервер не выдал идентификатор проверки.');
      }
      if (!mounted) return;
      setState(() {
        challengeId = id;
        message = 'Код запрошен. Введи полученный код подтверждения.';
      });
    } catch (_) {
      if (mounted) setState(() => message = 'Не удалось запросить код. Проверь подключение и данные.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> verifyCode() async {
    final id = challengeId;
    if (busy || id == null) return;
    setState(() {
      busy = true;
      message = '';
    });
    try {
      final result = await post('/native-auth/verify-code', {
        'challenge_id': id,
        'code': code.text.trim(),
      });
      final token = result['access_token'];
      final userId = result['user_id'];
      final tokenType = result['token_type'];
      final expiresIn = result['expires_in'];
      if (result['verified'] != true ||
          token is! String || token.length < 40 ||
          userId is! String || userId.isEmpty ||
          tokenType != 'Bearer' ||
          expiresIn is! int || expiresIn <= 0) {
        throw const FormatException('Сервер не выдал корректную сессию.');
      }
      if (!mounted) return;
      setState(() {
        sessionToken = token;
        signedInUserId = userId;
        sessionExpiry = DateTime.now().add(Duration(seconds: expiresIn));
        message = '';
        challengeId = null;
        code.clear();
      });
    } catch (_) {
      if (mounted) setState(() => message = 'Код не подтверждён. Проверь код или срок действия.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void signOut() {
    setState(() {
      sessionToken = null;
      signedInUserId = null;
      sessionExpiry = null;
      challengeId = null;
      code.clear();
      message = '';
    });
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    // The token remains only in process memory; app restart requires sign-in.
    // Server revocation and durable secure storage are separate future steps.
    final active = sessionToken != null &&
        signedInUserId != null &&
        sessionExpiry != null &&
        DateTime.now().isBefore(sessionExpiry!);
    if (active) {
      return Scaffold(
        appBar: AppBar(title: const Text('PRIVATE DRIVE'), actions: [languageSwitcher()]),
        body: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.verified_user_outlined, color: gold, size: 64),
                    const SizedBox(height: 20),
                    Text(tr('Вход выполнен', 'Prisijungta', 'Signed in'),
                        style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 12),
                    Text(tr('Аккаунт подтверждён. Это тестовый экран авторизации. Кабина пилота и интерфейс пассажира подключаются отдельно.',
                            'Paskyra patvirtinta. Tai bandomasis prisijungimo ekranas.',
                            'Account verified. This is a demo sign-in screen.'),
                        textAlign: TextAlign.center),
                    const SizedBox(height: 16),
                    Text('Аккаунт: ${signedInUserId!}', textAlign: TextAlign.center),
                    const SizedBox(height: 24),
                    FilledButton(onPressed: signOut,
                      child: Text(tr('Выйти', 'Atsijungti', 'Sign out'))),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE'), actions: [languageSwitcher()]),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                const SizedBox(height: 16),
                const PrivateDriveBrandLogo(size: 132, transparentBackground: true),
                const SizedBox(height: 18),
                Text(tr('Добро пожаловать', 'Sveiki atvykę', 'Welcome'),
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                Text(tr('Независимый вход без Telegram',
                    'Nepriklausomas prisijungimas be Telegram',
                    'Independent sign-in without Telegram'),
                    textAlign: TextAlign.center),
                const SizedBox(height: 8),
                const Text(
                  'Версия 0.2.18 · сборка 2026111918 · ДЕМО',
                  key: Key('app-demo-version'),
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 12, color: gold),
                ),
                const SizedBox(height: 20),
                TextField(
                  controller: destination,
                  enabled: !busy && challengeId == null,
                  keyboardType: TextInputType.phone,
                  decoration: InputDecoration(
                    labelText: tr('Телефон в формате +370...',
                      'Telefono numeris +370...', 'Phone number +370...'),
                    border: const OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 18),
                if (challengeId == null)
                  FilledButton(
                    onPressed: busy || apiBaseUrl.isEmpty ? null : requestCode,
                    child: Text(tr('Получить код', 'Gauti kodą', 'Get code')),
                  )
                else ...[
                  TextField(
                    controller: code,
                    enabled: !busy,
                    maxLength: 6,
                    onChanged: (_) => setState(() {}),
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: tr('Код подтверждения',
                        'Patvirtinimo kodas', 'Verification code'),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  FilledButton(
                    onPressed: busy || !RegExp(r'^\d{6}$').hasMatch(code.text.trim())
                        ? null : verifyCode,
                    child: Text(tr('Подтвердить', 'Patvirtinti', 'Verify')),
                  ),
                  TextButton(
                    onPressed: busy ? null : () => setState(() {
                      challengeId = null;
                      code.clear();
                      message = '';
                    }),
                    child: Text(tr('Изменить контакт', 'Keisti kontaktą', 'Change contact')),
                  ),
                ],
                if (busy) const Center(child: CircularProgressIndicator()),
                if (message.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(message, textAlign: TextAlign.center),
                  ),
                if (apiBaseUrl.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 20),
                    child: Text(
                      'Тестовая сборка: сервер авторизации не подключён. '
                      'Отправка SMS выключена.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: gold),
                    ),
                  ),
                if (apiBaseUrl.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: OutlinedButton(
                      key: const Key('open-offline-demo'),
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(builder: (_) => const PrivateDriveDemo()),
                      ),
                      child: Text(tr('Посмотреть тестовые интерфейсы',
                          'Atidaryti bandomąsias sąsajas', 'Open demo interfaces')),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
