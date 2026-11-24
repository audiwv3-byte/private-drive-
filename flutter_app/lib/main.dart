import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:http/http.dart' as http;
import 'remote_sync_demo.dart';
import 'remote_sync_client.dart';
import 'demo_interfaces.dart';
import 'demo_backup_page.dart';
import 'brand_logo.dart';
import 'private_drive_bright_backdrop.dart';
import 'app_language.dart';
import 'permissions_onboarding.dart';
import 'company_info.dart';
import 'pd_http_api.dart';
import 'pilot_identity_api.dart';
import 'pilot_photo_capture.dart';
import 'native_cabin_entry.dart';
import 'native_closed_invite_api.dart';
import 'native_session.dart';
import 'native_logout_api.dart';
import 'native_session_vault.dart';
import 'native_session_manager.dart';

const apiBaseUrl = String.fromEnvironment('PD_NATIVE_AUTH_API_URL');
const closedPilotInviteBuild = bool.fromEnvironment('PD_CLOSED_PILOT_INVITE_ENTRY');
const pilotAccountInviteBuild = closedPilotInviteBuild &&
    bool.fromEnvironment('PD_NATIVE_PILOT_INVITE_ONBOARDING') &&
    bool.fromEnvironment('PD_NATIVE_PILOT_ASSIGNMENT');
// Opt-in only for the isolated static Safari/Android browser test artifact.
// No production auth URL, payment gateway or automatic backend connection.
const isolatedWebPreview = bool.fromEnvironment('PD_ISOLATED_WEB_PREVIEW');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await PdSystemPilotPhotoCapture.discardLostCapture();
  await pdLanguage.restore();
  runApp(const PrivateDriveApp());
}

class PrivateDriveApp extends StatelessWidget {
  const PrivateDriveApp({super.key, this.enableOfflinePreview = false});

  final bool enableOfflinePreview;

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
      home: closedPilotInviteBuild && (kIsWeb || enableOfflinePreview ||
              isolatedWebPreview || const bool.fromEnvironment('PD_INTERNAL_QA') ||
              const bool.fromEnvironment('PD_ISOLATED_NATIVE_SYNC') ||
              apiBaseUrl != PdClosedInviteApi.stagingBaseUrl)
          ? const Scaffold(body: Center(
              child: Text('В этой сборке не настроен безопасный тестовый вход.')))
          : kIsWeb && isolatedWebPreview
          ? const RemoteSyncDemo()
          : enableOfflinePreview
          // Explicit developer harness only. Normal launch starts with cabins.
          ? const PdPermissionsFirstLaunch(
              child: NativeSignInScreen(enableOfflinePreview: true),
            )
          : PdNativeCabinEntry(
              closedInviteOnly: closedPilotInviteBuild,
              allowInvitedPilot: pilotAccountInviteBuild,
              signInBuilder: (_, role, onAuthenticated) =>
                  closedPilotInviteBuild && role == 'dispatcher'
                  ? const Center(child: Text(
                      'Диспетчер работает в веб-кабинете.',
                      textAlign: TextAlign.center))
                  : closedPilotInviteBuild && role == 'pilot' &&
                      !pilotAccountInviteBuild
                  ? const Center(child: Text(
                      'В этой сборке приглашения доступны только пассажирам.',
                      textAlign: TextAlign.center))
                  : NativeSignInScreen(
                      enableOfflinePreview: enableOfflinePreview,
                      allowGuestEntry: role == 'passenger',
                      enableClosedInvite: closedPilotInviteBuild,
                      pilotInvite: pilotAccountInviteBuild && role == 'pilot',
                      onAuthenticated: onAuthenticated,
                    ),
              identityApiBuilder: (session) => PdIdentityApi(
                baseUrl: apiBaseUrl, token: session.token),
              logoutApi: const PdNativeLogoutApi(baseUrl: apiBaseUrl),
              sessionManager: const PdNativeSessionManager(
                baseUrl: apiBaseUrl, vault: PdNativeSessionVault()),
              // Isolated integration QA is opt-in and separate from live
              // dispatch. Requires a synthetic server verifying this SAME
              // native bearer token on every request.
              isolatedSyncGatewayBuilder:
                const bool.fromEnvironment('PD_ISOLATED_NATIVE_SYNC') &&
                const String.fromEnvironment('PD_ISOLATED_SYNC_API_URL').isNotEmpty
                  ? (session, cabin) => RemoteDemoClient(
                      const String.fromEnvironment('PD_ISOLATED_SYNC_API_URL'),
                      session.token, cabin: cabin,
                    )
                  : null,
            ),
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
    this.enableClosedInvite = false,
    this.pilotInvite = false,
    this.onAuthenticated,
  });

  final String authApiUrl;
  final bool enableOfflinePreview;
  final http.Client? httpClient;
  final bool allowGuestEntry;
  final bool enableClosedInvite;
  final bool pilotInvite;
  final ValueChanged<PdNativeSession>? onAuthenticated;

  @override
  State<NativeSignInScreen> createState() => _NativeSignInScreenState();
}

class _NativeSignInScreenState extends State<NativeSignInScreen> {
  final destination = TextEditingController();
  final code = TextEditingController();
  final inviteCode = TextEditingController();
  bool busy = false;
  bool loggingOut = false;
  bool _guest = false;
  bool _acknowledgedLegal = false;
  // Authentication belongs to the Russian-only shared/native shell.
  // Passenger language selection is available inside the passenger cabin.
  String tr(String ru, String lt, String en) => ru;
  String? challengeId;
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
    inviteCode.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> post(String path, Map<String, String> payload) {
    final uri = PdHttpApi.secureUri(widget.authApiUrl, path);
    return const PdHttpApi().postJson(uri, payload, client: widget.httpClient);
  }

  PdClosedInviteApi get _inviteApi => PdClosedInviteApi(
      baseUrl: widget.authApiUrl, client: widget.httpClient,
      pilotInvite: widget.enableClosedInvite && widget.pilotInvite);

  bool get _closedInviteEntry => widget.enableClosedInvite &&
      widget.onAuthenticated != null && _inviteApi.enabled;

  Future<void> _redeemInvite() async {
    if (!_closedInviteEntry || busy || !_acknowledgedLegal) return;
    final value = inviteCode.text.trim();
    if (!PdClosedInviteApi.validCode(value)) return;
    setState(() {
      busy = true;
      message = '';
    });
    try {
      final session = await _inviteApi.redeem(value);
      if (!mounted || !_closedInviteEntry) return;
      inviteCode.clear();
      widget.onAuthenticated!(session);
    } on PdHttpStatusException catch (error) {
      if (mounted && _closedInviteEntry) setState(() {
        if (error.statusCode == 401) inviteCode.clear();
        message = switch (error.statusCode) {
          401 => 'Приглашение недействительно, просрочено или уже использовано.',
          429 => 'Слишком много попыток. Подожди немного и повтори.',
          _ => 'Вход по приглашению временно недоступен.',
        };
      });
    } catch (_) {
      if (mounted) setState(() => message = 'Не удалось подтвердить приглашение.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> requestCode() async {
    if (widget.enableClosedInvite || busy || !_acknowledgedLegal) return;
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
    } on PdHttpStatusException catch (error) {
      if (mounted) setState(() => message = switch (error.errorCode) {
        'sms_disabled' => 'Вход по SMS сейчас отключён на тестовом сервере. '
            'Код не отправлен. Во внутренней сборке можно продолжить как гость.',
        'sms_unavailable' => 'Сервис SMS временно недоступен. Код не отправлен. Повтори позже.',
        'invalid_phone' => 'Проверь номер: укажи код страны, например +370, и номер телефона.',
        'try_later' => 'Слишком частые запросы. Подожди минуту и повтори.',
        _ => 'Сервер входа временно недоступен. Повтори позже.',
      });
    } catch (_) {
      if (mounted) setState(() => message = 'Сервер входа не ответил вовремя. '
          'Повтори запрос позже или продолжи как гость во внутренней сборке.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> verifyCode() async {
    final id = challengeId;
    if (widget.enableClosedInvite || busy || id == null) return;
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
      final role = result['role'];
      if (result['verified'] != true ||
          token is! String || token.length < 40 ||
          userId is! String || userId.isEmpty ||
          tokenType != 'Bearer' ||
          !const {'passenger', 'admin', 'pilot', 'dispatcher', 'pilot_dispatcher'}.contains(role) ||
          expiresIn is! int || expiresIn <= 0) {
        throw const FormatException('Сервер не выдал корректную сессию.');
      }
      if (!mounted) return;
      final expiry = DateTime.now().add(Duration(seconds: expiresIn));
      final onAuthenticated = widget.onAuthenticated;
      if (onAuthenticated != null) {
        onAuthenticated(PdNativeSession(token: token, userId: userId,
          role: role as String, expiresAt: expiry));
        return;
      }
      setState(() {
        sessionToken = token;
        signedInUserId = userId;
        signedInRole = role as String;
        showVerifiedIdentity = true;
        sessionExpiry = expiry;
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
      _guest = false;
      sessionToken = null;
      signedInUserId = null;
      signedInRole = null;
      selectedStaffRole = null;
      showVerifiedIdentity = false;
      sessionExpiry = null;
      challengeId = null;
      code.clear();
      message = '';
    });
  }

  Future<void> remoteSignOut() async {
    if (loggingOut) return;
    final token = sessionToken;
    if (token == null) {
      signOut();
      return;
    }
    setState(() => loggingOut = true);
    try {
      await PdNativeLogoutApi(baseUrl: widget.authApiUrl,
        client: widget.httpClient).revokeCurrentDevice(token);
      if (!mounted || sessionToken != token) return;
      signOut();
    } catch (_) {
      if (mounted) {
        setState(() => message =
          'Не удалось завершить сеанс на сервере. Попробуй ещё раз.');
      }
    } finally {
      if (mounted) setState(() => loggingOut = false);
    }
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
            passengerOnly: true,
            storageScope: 'internal-guest',
            onSignOut: signOut,
            onBackToCabinets: signOut,
          )),
        ])),
      );
    }
    // The token remains only in process memory; app restart requires sign-in.
    // Durable secure storage is a separate future step.
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
                      onPressed: loggingOut ? null : remoteSignOut,
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
      final canDispatch = const {'admin', 'dispatcher', 'pilot_dispatcher'}
          .contains(serverRole);
      final role = selectedStaffRole;
      if (role == null ||
          (role == 'pilot' && !canPilot) ||
          (role == 'dispatcher' && !canDispatch) ||
          !const {'passenger', 'pilot', 'dispatcher'}.contains(role)) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('PRIVATE DRIVE'),
            actions: [
              IconButton(
                tooltip: 'Выйти',
                icon: const Icon(Icons.logout),
                onPressed: loggingOut ? null : remoteSignOut,
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
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      key: const Key('authorized-open-dispatcher'),
                      onPressed: canDispatch
                          ? () => setState(() => selectedStaffRole = 'dispatcher')
                          : null,
                      icon: const Icon(Icons.support_agent_outlined),
                      label: const Text('Диспетчер'),
                    ),
                    const SizedBox(height: 16),
                    const Text('Кабинеты пилота и диспетчера доступны только '
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
        child: PrivateDriveDemo(
        key: ValueKey('$role-${signedInUserId!}'),
        storageScope: signedInUserId,
        adminOnly: role == 'dispatcher',
        pilotOnly: role == 'pilot',
        passengerOnly: role == 'passenger',
        onSignOut: remoteSignOut,
        onBackToCabinets: () => setState(() => selectedStaffRole = null),
      ));
    }
    return Scaffold(
      appBar: AppBar(
          title: const Text('PRIVATE DRIVE'),
          actions: [
            IconButton(
              key: const Key('native-permission-settings'),
              tooltip: 'Разрешения приложения',
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
                Text(tr('Независимый вход без Telegram',
                    'Nepriklausomas prisijungimas be Telegram',
                    'Independent sign-in without Telegram'),
                    textAlign: TextAlign.center),
                const SizedBox(height: 8),
                const Text(
                  'Версия 0.2.27 · сборка 2026112103',
                  key: Key('app-demo-version'),
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 12, color: gold),
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
                if (!widget.enableClosedInvite && const bool.fromEnvironment('PD_INTERNAL_QA') && widget.allowGuestEntry) ...[
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
                if (widget.enableClosedInvite)
                  TextField(
                    key: const Key('closed-pilot-invite-field'),
                    controller: inviteCode,
                    enabled: _closedInviteEntry && !busy,
                    obscureText: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    enableIMEPersonalizedLearning: false,
                    textCapitalization: TextCapitalization.none,
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                      labelText: 'Код приглашения',
                      border: OutlineInputBorder(),
                    ),
                  )
                else TextField(
                  controller: destination,
                  enabled: !busy && challengeId == null,
                  keyboardType: TextInputType.phone,
                  decoration: InputDecoration(
                    labelText: tr('Телефон в формате +370...',
                      'Telefono numeris +370...', 'Phone number +370...'),
                    border: const OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                if (challengeId == null) ...[
                  CheckboxListTile(
                    key: const Key('native-legal-acknowledgement'),
                    controlAffinity: ListTileControlAffinity.leading,
                    value: _acknowledgedLegal,
                    onChanged: busy ? null : (v) =>
                        setState(() => _acknowledgedLegal = v ?? false),
                    title: const Text('Я ознакомился с условиями сервиса '
                      'и политикой конфиденциальности'),
                    subtitle: const Text(
                      'Это подтверждение ознакомления, не согласие '
                      'на рекламу или необязательное отслеживание.'),
                  ),
                  TextButton.icon(
                    key: const Key('native-open-legal-documents'),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => const CompanyInfoPage())),
                    icon: const Icon(Icons.gavel_outlined),
                    label: const Text('Условия, конфиденциальность, отмена и возврат'),
                  ),
                ],
                const SizedBox(height: 8),
                if (widget.enableClosedInvite)
                  FilledButton(
                    key: const Key('closed-pilot-invite-submit'),
                    onPressed: !_closedInviteEntry || busy || !_acknowledgedLegal ||
                        !PdClosedInviteApi.validCode(inviteCode.text.trim())
                        ? null : _redeemInvite,
                    child: const Text('Войти по приглашению'),
                  )
                else if (challengeId == null)
                  FilledButton(
                    onPressed: busy || widget.authApiUrl.isEmpty || !_acknowledgedLegal
                        ? null : requestCode,
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
                if (widget.enableClosedInvite && !_closedInviteEntry)
                  const Text('В этой сборке не настроен безопасный тестовый вход.',
                      textAlign: TextAlign.center),
                if (busy) const Center(child: CircularProgressIndicator()),
                if (message.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(message, textAlign: TextAlign.center),
                  ),
                if (widget.authApiUrl.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 20),
                    child: Text(
                      'В этой сборке сервер авторизации не подключён.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: gold),
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

