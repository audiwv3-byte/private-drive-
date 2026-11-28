import 'dart:async';
import 'native_server_cabin.dart';
import 'native_pilot_orders.dart';
import 'native_orders_api.dart';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import 'remote_sync_demo.dart';
import 'demo_interfaces.dart';
import 'demo_backup_page.dart';
import 'brand_logo.dart';
import 'private_drive_bright_backdrop.dart';
import 'app_language.dart';
import 'first_launch_language_page.dart';
import 'permissions_onboarding.dart';
import 'company_info.dart';
import 'pd_http_api.dart';
import 'pilot_identity_api.dart';
import 'pilot_photo_capture.dart';
import 'native_cabin_entry.dart';
import 'native_session.dart';
import 'native_session_store.dart';

const apiBaseUrl = PdHttpApi.configuredOrigin;
// Opt-in only for the isolated static Safari/Android browser test artifact.
// No production auth URL, payment gateway or automatic backend connection.
const isolatedWebPreview = bool.fromEnvironment('PD_ISOLATED_WEB_PREVIEW');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (!pdLocalQaEntryEnabled) {
    await PdSystemPilotPhotoCapture.discardLostCapture();
  }
  await pdLanguage.restore();
  runApp(const PrivateDriveApp());
}

class PrivateDriveApp extends StatelessWidget {
  const PrivateDriveApp({
    super.key,
    this.enableOfflinePreview = false,
    this.language,
  });

  final bool enableOfflinePreview;
  final PdLanguage? language;

  Widget _home() {
    if (kIsWeb && isolatedWebPreview) return const RemoteSyncDemo();
    if (enableOfflinePreview) {
      return const PdPermissionsFirstLaunch(
        child: NativeSignInScreen(enableOfflinePreview: true),
      );
    }
    final entry = PdNativeCabinEntry(
      signInBuilder: (_, role, onAuthenticated) => NativeSignInScreen(
        allowGuestEntry: role == 'passenger',
        onAuthenticated: onAuthenticated,
      ),
      identityApiBuilder: (session) =>
          PdIdentityApi(baseUrl: apiBaseUrl, token: session.token),
      sessionStore: !kIsWeb && apiBaseUrl.isNotEmpty &&
          (defaultTargetPlatform == TargetPlatform.android ||
           defaultTargetPlatform == TargetPlatform.iOS)
          ? PdNativeSessionStore(apiBaseUrl) : null,
    );
    if (pdLocalQaEntryEnabled) return entry;
    return PdFirstLaunchLanguage(child: entry);
  }

  @override
  Widget build(BuildContext context) {
    return PdLanguageScope(
      language: language ?? pdLanguage,
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
        home: _home(),
      ),
    );
  }
}

class NativeSignInScreen extends StatefulWidget {
  const NativeSignInScreen({
    super.key,
    this.authApiUrl = apiBaseUrl,
    this.enableOfflinePreview = false,
    this.httpClient,
    this.allowGuestEntry = true,
    this.onAuthenticated,
    this.telegramLauncher,
  });

  final String authApiUrl;
  final bool enableOfflinePreview;
  final http.Client? httpClient;
  final bool allowGuestEntry;
  final ValueChanged<PdNativeSession>? onAuthenticated;
  final Future<bool> Function(Uri)? telegramLauncher;

  @override
  State<NativeSignInScreen> createState() => _NativeSignInScreenState();
}

class _NativeSignInScreenState extends State<NativeSignInScreen> {
  final destination = TextEditingController();
  final code = TextEditingController();
  bool busy = false;
  bool _guest = false;
  bool _acknowledgedLegal = false;
  String _language = 'RU';
  String tr(String ru, String lt, String en) => switch (_language) {
    'LT' => lt,
    'EN' => en,
    _ => ru,
  };

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _language = PdLanguageScope.of(context).value;
  }
  String? challengeId;
  (String, String)? telegramAttempt;
  String message = '';
  String? sessionToken;
  String? signedInUserId;
  String? signedInRole;
  String? selectedStaffRole;
  bool showVerifiedIdentity = false;
  DateTime? sessionExpiry;

  @override
  void dispose() {
    destination.dispose();
    code.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> post(String path, Map<String, String> payload) {
    final uri = PdHttpApi.secureUri(widget.authApiUrl, path);
    return const PdHttpApi().postJson(uri, payload, client: widget.httpClient,
        timeout: const Duration(seconds: 60));
  }

  Future<void> requestCode() async {
    if (busy || !_acknowledgedLegal) return;
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
        message = tr('Код запрошен. Введи полученный код подтверждения.',
            'Kodas išsiųstas. Įvesk gautą patvirtinimo kodą.',
            'Code requested. Enter the verification code you received.');
      });
    } on PdHttpStatusException catch (error) {
      if (mounted) setState(() => message = switch (error.errorCode) {
        'sms_disabled' => tr(
            'Вход по SMS сейчас отключён на тестовом сервере. '
                'Код не отправлен. Во внутренней сборке можно продолжить как гость.',
            'Bandomajame serveryje prisijungimas SMS žinute išjungtas. '
                'Kodas neišsiųstas. Vidinėje versijoje galima tęsti kaip svečiui.',
            'SMS sign-in is disabled on the test server. The code was not sent. '
                'Guest access is available in the internal build.'),
        'sms_unavailable' => tr(
            'Сервис SMS временно недоступен. Код не отправлен. Повтори позже.',
            'SMS paslauga laikinai nepasiekiama. Kodas neišsiųstas. Bandyk vėliau.',
            'SMS service is temporarily unavailable. The code was not sent. Try again later.'),
        'invalid_phone' => tr(
            'Проверь номер: укажи код страны, например +370, и номер телефона.',
            'Patikrink numerį. Įvesk šalies kodą, pavyzdžiui, +370, ir telefono numerį.',
            'Check your number. Include the country code, such as +370.'),
        'sms_number_not_enabled' => tr(
            'Этот номер не включён в SMS-тест. Можно войти через Telegram.',
            'Šis numeris neįtrauktas į SMS testą. Gali prisijungti per „Telegram“.',
            'This number is not enabled for SMS testing. You can sign in with Telegram.'),
        'try_later' => tr(
            'Слишком частые запросы. Подожди минуту и повтори.',
            'Per daug užklausų. Palauk minutę ir bandyk dar kartą.',
            'Too many requests. Wait a minute and try again.'),
        _ => tr('Сервер входа временно недоступен. Повтори позже.',
            'Prisijungimo serveris laikinai nepasiekiamas. Bandyk vėliau.',
            'The sign-in server is temporarily unavailable. Try again later.'),
      });
    } on TimeoutException {
      if (mounted) setState(() => message = 'QA: время ожидания ответа истекло · ${Uri.tryParse(widget.authApiUrl)?.host}');
    } catch (error) {
      if (mounted) setState(() => message = 'QA: ошибка входа · ${error.runtimeType} · ${Uri.tryParse(widget.authApiUrl)?.host}');
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
      _completeSignIn(result);
    } catch (_) {
      if (mounted) setState(() => message = tr(
          'Код не подтверждён. Проверь код или срок действия.',
          'Kodas nepatvirtintas. Patikrink kodą ir jo galiojimo laiką.',
          'The code could not be verified. Check the code and its expiry.'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _completeSignIn(Map<String, dynamic> result) {
    if (!mounted) return;
    final session = PdNativeSession.fromApi(result);
    final onAuthenticated = widget.onAuthenticated;
    if (onAuthenticated != null) {
      onAuthenticated(session);
      return;
    }
    setState(() {
      sessionToken = session.token;
      signedInUserId = session.userId;
      signedInRole = session.role;
      sessionExpiry = session.expiresAt;
      showVerifiedIdentity = true;
      _resetChallenge();
    });
  }

  void _resetChallenge() {
    challengeId = null;
    telegramAttempt = null;
    code.clear();
    message = '';
  }

  Future<void> _startTelegram() async {
    if (const bool.fromEnvironment('PD_ISOLATED_DEVICE_QA')) return;
    if (busy || !_acknowledgedLegal) return;
    setState(() {
      busy = true;
      _resetChallenge();
    });
    try {
      final random = Random.secure();
      final secret = base64UrlEncode(
        List.generate(32, (_) => random.nextInt(256)),
      ).replaceAll('=', '');
      final result = await post('/native-auth/telegram/start', {
        'app_secret': secret,
        'language': _language,
      });
      final state = result['state'];
      final url = result['authorization_url'];
      final uri = url is String ? Uri.tryParse(url) : null;
      if (state is! String || !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(state) ||
          uri == null || uri.scheme != 'https' || uri.host != 'oauth.telegram.org' ||
          uri.port != 443 || uri.path != '/auth' || uri.userInfo.isNotEmpty ||
          uri.queryParameters['state'] != state) {
        throw const FormatException('Invalid Telegram authorization response.');
      }
      if (!mounted) return;
      final opened = await (widget.telegramLauncher?.call(uri) ??
          launchUrl(uri, mode: LaunchMode.externalApplication));
      if (!opened) throw StateError('Telegram authorization could not be opened.');
      if (mounted) setState(() => telegramAttempt = (state, secret));
    } on PdHttpStatusException catch (error) {
      if (mounted) setState(() => message = error.errorCode == 'telegram_disabled'
          ? tr('Вход через Telegram пока недоступен. Попробуй SMS.',
              'Prisijungimas per „Telegram“ kol kas nepasiekiamas. Bandyk SMS.',
              'Telegram sign-in is currently unavailable. Try SMS.')
          : _telegramStartError());
    } catch (_) {
      if (mounted) setState(() => message = _telegramStartError());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String _telegramStartError() => tr(
    'Не удалось открыть вход через Telegram. Повтори или выбери SMS.',
    'Nepavyko atidaryti prisijungimo per „Telegram“. Bandyk dar kartą arba rinkis SMS.',
    'Could not open Telegram sign-in. Try again or use SMS.',
  );

  Future<void> _finishTelegram() async {
    final attempt = telegramAttempt;
    final digits = code.text.trim();
    if (busy || attempt == null || !RegExp(r'^[0-9]{8}$').hasMatch(digits)) return;
    setState(() {
      busy = true;
      message = '';
    });
    try {
      final (state, secret) = attempt;
      final result = await post('/native-auth/telegram/finish', {
        'state': state,
        'app_secret': secret,
        'code': digits,
      });
      _completeSignIn(result);
    } on PdHttpStatusException catch (error) {
      if (mounted) setState(() => message = error.errorCode == 'telegram_link_conflict'
          ? tr('Этот Telegram связан с другим аккаунтом. Используй вход по SMS.',
              'Ši „Telegram“ paskyra susieta su kita paskyra. Prisijunk SMS žinute.',
              'This Telegram account is linked to another account. Sign in with SMS.')
          : error.errorCode == 'telegram_code_invalid'
          ? tr('Проверь код. Если он истёк, начни вход заново.',
              'Patikrink kodą. Jei jis nebegalioja, pradėk iš naujo.',
              'Check the code. If it expired, start sign-in again.')
          : _telegramFinishError());
    } catch (_) {
      if (mounted) setState(() => message = _telegramFinishError());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String _telegramFinishError() => tr(
    'Не удалось завершить вход. Повтори попытку.',
    'Nepavyko užbaigti prisijungimo. Bandyk dar kartą.',
    'Could not complete sign-in. Try again.',
  );

  void signOut() {
    setState(() {
      _guest = false;
      sessionToken = null;
      signedInUserId = null;
      signedInRole = null;
      selectedStaffRole = null;
      showVerifiedIdentity = false;
      sessionExpiry = null;
      _resetChallenge();
    });
  }

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFDDC184);
    if (const bool.fromEnvironment('PD_INTERNAL_QA') && _guest) {
      return Scaffold(
        body: SafeArea(child: Column(children: [
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text('Гостевой доступ · внутренний тест. '
              'Телефон не подтверждён. Заказы сохраняются только на этом устройстве.',
              key: Key('internal-guest-status'), textAlign: TextAlign.center),
          ),
          Expanded(child: PrivateDriveDemo(
            key: const ValueKey('internal-guest-passenger'),
                    onSignOut: signOut,
            onBackToCabinets: signOut,
          )),
        ])),
      );
    }
    // The token remains only in process memory; app restart requires sign-in.
    // Server revocation and durable secure storage are separate future steps.
    final active = sessionToken != null &&
        signedInUserId != null &&
        sessionExpiry != null &&
        DateTime.now().isBefore(sessionExpiry!);
    if (active) {
      if (showVerifiedIdentity) {
        // The ID comes only from the completed server-side OTP verification.
        // Never expose the bearer token or infer privileges from an ID.
        return Scaffold(
          appBar: AppBar(title: const Text('PRIVATE DRIVE · Аккаунт')),
          body: SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: ListView(
                  shrinkWrap: true,
                  padding: const EdgeInsets.all(24),
                  children: [
                    const Icon(Icons.verified_user_outlined,
                      size: 56, color: gold),
                    const SizedBox(height: 16),
                    const Text('Телефон подтверждён',
                      key: Key('native-account-verified'),
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 16),
                    const Text('Твой ID в PRIVATE DRIVE:'),
                    SelectableText(signedInUserId!,
                      key: const Key('native-verified-user-id')),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      key: const Key('native-copy-user-id'),
                      onPressed: () => Clipboard.setData(
                        ClipboardData(text: signedInUserId!)),
                      icon: const Icon(Icons.copy),
                      label: const Text('Скопировать ID'),
                    ),
                    const SizedBox(height: 12),
                    const Text('Этот ID не предоставляет права администратора. '
                      'Назначение главного администратора выполняется отдельно '
                      'и только на защищённом сервере. Никому не передавай '
                      'SMS-код или токен входа.'),
                    const SizedBox(height: 24),
                    FilledButton(
                      key: const Key('native-continue-to-cabin'),
                      onPressed: () => setState(() => showVerifiedIdentity = false),
                      child: const Text('Перейти в приложение'),
                    ),
                    TextButton(
                      onPressed: signOut,
                      child: const Text('Выйти'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      }
      // Role selection is always explicit after verified sign-in. The server
      // remains authoritative for privileged role access.
      final serverRole = signedInRole!;
      final canPilot = const {'admin', 'pilot', 'pilot_dispatcher'}
          .contains(serverRole);
      final role = selectedStaffRole;
      if (role == null ||
          (role == 'pilot' && !canPilot) ||
          !const {'passenger', 'pilot'}.contains(role)) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('PRIVATE DRIVE'),
            actions: [
              IconButton(
                tooltip: 'Выйти',
                icon: const Icon(Icons.logout),
                onPressed: signOut,
              ),
            ],
          ),
          body: SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: ListView(
                  shrinkWrap: true,
                  padding: const EdgeInsets.all(24),
                  children: [
                    const Icon(Icons.dashboard_customize_outlined,
                        size: 64, color: gold),
                    const SizedBox(height: 16),
                    const Text('Выбери кабинет',
                      key: Key('authorized-role-selection'),
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 24),
                    FilledButton.icon(
                      key: const Key('authorized-open-passenger'),
                      onPressed: () => setState(() => selectedStaffRole = 'passenger'),
                      icon: const Icon(Icons.person_outline),
                      label: const Text('Пассажир'),
                    ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      key: const Key('authorized-open-pilot'),
                      onPressed: canPilot
                          ? () => setState(() => selectedStaffRole = 'pilot')
                          : null,
                      icon: const Icon(Icons.directions_car_outlined),
                      label: const Text('Пилот'),
                    ),
                    const SizedBox(height: 16),
                    const Text('Кабинет пилота доступен только '
                        'с правами, подтверждёнными сервером.',
                        textAlign: TextAlign.center),
                  ],
                ),
              ),
            ),
          ),
        );
      }
      return PdIdentityScope(
        api: PdIdentityApi(baseUrl: widget.authApiUrl, token: sessionToken!, client: widget.httpClient),
        child: NativeServerCabin(
        key: ValueKey('$role-${signedInUserId!}'),
        pilotApi: role == 'pilot'
            ? NativePilotOrdersApi(baseUrl: widget.authApiUrl, token: sessionToken!, client: widget.httpClient)
            : null,
        ordersApi: role == 'passenger'
            ? NativeOrdersApi(widget.authApiUrl, sessionToken!, client: widget.httpClient)
            : null,
        onSignOut: signOut,
        onBackToCabinets: () => setState(() => selectedStaffRole = null),
      ));
    }
    return Scaffold(
      appBar: AppBar(
          title: const Text('PRIVATE DRIVE'),
          actions: [
            IconButton(
              key: const Key('native-permission-settings'),
              tooltip: tr('Разрешения приложения', 'Programėlės leidimai',
                  'App permissions'),
              icon: const Icon(Icons.settings_outlined),
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const PdPermissionSettingsPage(),
                ),
              ),
            ),
          ],
        ),
      body: Stack(
        children: [
          const Positioned.fill(child: PrivateDriveBrightBackdrop()),
          SafeArea(
            child: Center(
              child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                const SizedBox(height: 16),
                const PrivateDriveBrandLogo(size: 156, transparentBackground: true),
                const SizedBox(height: 18),
                Text(tr('Добро пожаловать', 'Sveiki atvykę', 'Welcome'),
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                Text(tr('Войди через Telegram или SMS',
                    'Prisijunk per „Telegram“ arba SMS žinute',
                    'Sign in with Telegram or SMS'),
                    textAlign: TextAlign.center),
                const SizedBox(height: 8),
                Text(
                  tr('Версия 0.2.27 · сборка 2026112103',
                      'Versija 0.2.27 · 2026112103 leidimas',
                      'Version 0.2.27 · build 2026112103'),
                  key: const Key('app-demo-version'),
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12, color: gold),
                ),
                if (widget.enableOfflinePreview && widget.authApiUrl.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: FilledButton(
                      key: const Key('open-offline-demo'),
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => const PrivateDriveDemo(),
                        ),
                      ),
                      child: const Text('Открыть тестовые кабинеты'),
                    ),
                  ),
                if (const bool.fromEnvironment('PD_INTERNAL_QA') && widget.allowGuestEntry) ...[
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    key: const Key('internal-guest-entry'),
                    onPressed: busy ? null : () {
                      signOut();
                      setState(() => _guest = true);
                    },
                    icon: const Icon(Icons.person_outline),
                    label: const Text('Продолжить как гость'),
                  ),
                  const Text('Пассажирский кабинет без SMS. Только внутренняя сборка.',
                    textAlign: TextAlign.center),
                ],
                const SizedBox(height: 20),
                if (telegramAttempt == null) ...[
                  TextField(
                    controller: destination,
                    enabled: !busy && challengeId == null,
                    keyboardType: TextInputType.phone,
                    autofillHints: const [AutofillHints.telephoneNumber],
                    decoration: InputDecoration(
                      labelText: tr('Телефон в формате +370...',
                        'Telefono numeris +370...', 'Phone number +370...'),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                if (challengeId == null && telegramAttempt == null) ...[
                  CheckboxListTile(
                    key: const Key('native-legal-acknowledgement'),
                    controlAffinity: ListTileControlAffinity.leading,
                    value: _acknowledgedLegal,
                    onChanged: busy ? null : (v) =>
                        setState(() => _acknowledgedLegal = v ?? false),
                    title: Text(tr(
                      'Я ознакомился с условиями сервиса и политикой конфиденциальности',
                      'Susipažinau su paslaugos sąlygomis ir privatumo politika',
                      'I have read the terms of service and privacy policy')),
                    subtitle: Text(tr(
                      'Это подтверждение ознакомления, не согласие '
                          'на рекламу или необязательное отслеживание.',
                      'Taip patvirtini, kad susipažinai su dokumentais. '
                          'Tai nėra sutikimas gauti reklamą ar būti sekamam.',
                      'This confirms that you have read the documents. It does '
                          'not opt you in to advertising or optional tracking.')),
                  ),
                  TextButton.icon(
                    key: const Key('native-open-legal-documents'),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => const CompanyInfoPage())),
                    icon: const Icon(Icons.gavel_outlined),
                    label: Text(tr(
                      'Условия, конфиденциальность, отмена и возврат',
                      'Sąlygos, privatumas, atšaukimas ir pinigų grąžinimas',
                      'Terms, privacy, cancellations and refunds')),
                  ),
                ],
                const SizedBox(height: 8),
                if (telegramAttempt != null) ...[
                  Text(tr(
                    'Разреши Telegram передать номер телефона, затем вернись сюда и введи код с открывшейся страницы.',
                    'Leisk „Telegram“ perduoti telefono numerį, tada grįžk čia ir įvesk puslapyje rodomą kodą.',
                    'Allow Telegram to share your phone number, then return here and enter the code shown in the browser.',
                  )),
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('native-telegram-code'),
                    controller: code,
                    enabled: !busy,
                    maxLength: 8,
                    onChanged: (_) => setState(() {}),
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: tr('Код из браузера', 'Kodas iš naršyklės', 'Code from browser'),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                  FilledButton(
                    key: const Key('native-telegram-finish'),
                    onPressed: busy || !RegExp(r'^[0-9]{8}$').hasMatch(code.text.trim())
                        ? null : _finishTelegram,
                    child: Text(tr('Войти', 'Prisijungti', 'Sign in')),
                  ),
                  TextButton(
                    onPressed: busy ? null : () => setState(_resetChallenge),
                    child: Text(tr('Вернуться к способам входа', 'Grįžti prie prisijungimo būdų',
                        'Back to sign-in options')),
                  ),
                ] else if (challengeId == null) ...[
                  FilledButton(
                    onPressed: busy || widget.authApiUrl.isEmpty || !_acknowledgedLegal
                        ? null : requestCode,
                    child: Text(tr('Получить код', 'Gauti kodą', 'Get code')),
                  ),
                  const SizedBox(height: 8),
                  OutlinedButton.icon(
                    key: const Key('native-telegram-start'),
                    onPressed: busy || widget.authApiUrl.isEmpty || !_acknowledgedLegal
                        ? null : _startTelegram,
                    icon: const Icon(Icons.send_outlined),
                    label: Text(tr('Войти через Telegram', 'Prisijungti per „Telegram“',
                        'Sign in with Telegram')),
                  ),
                ] else ...[
                  TextField(
                    controller: code,
                    enabled: !busy,
                    maxLength: 6,
                    onChanged: (_) => setState(() {}),
                    keyboardType: TextInputType.number,
                    autofillHints: const [AutofillHints.oneTimeCode],
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
                    onPressed: busy ? null : () => setState(_resetChallenge),
                    child: Text(tr('Изменить контакт', 'Keisti kontaktą', 'Change contact')),
                  ),
                ],
                if (busy) const Center(child: CircularProgressIndicator()),
                if (message.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(message, textAlign: TextAlign.center),
                  ),
                if (widget.authApiUrl.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 20),
                    child: Text(tr(
                      'В этой сборке сервер авторизации не подключён.',
                      'Šioje versijoje prisijungimo serveris neprijungtas.',
                      'The sign-in server is not connected in this build.'),
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: gold),
                    ),
                  ),
                if (!kIsWeb && widget.enableOfflinePreview && widget.authApiUrl.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: OutlinedButton.icon(
                      key: const Key('open-demo-backup'),
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(builder: (_) =>
                          const DemoBackupPage()),
                      ),
                      icon: const Icon(Icons.backup_outlined),
                      label: const Text('Резервная копия · DEMO'),
                    ),
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

