import 'dart:async';
import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'brand_logo.dart';
import 'private_drive_bright_backdrop.dart';
import 'demo_interfaces.dart';
import 'permissions_onboarding.dart';
import 'native_session.dart';
import 'pilot_identity_api.dart';
import 'pilot_identity_notice_page.dart';
import 'remote_sync_demo.dart';
import 'remote_sync_client.dart';

typedef PdSignInBuilder = Widget Function(BuildContext context, String role,
    ValueChanged<PdNativeSession> onAuthenticated);

const _localQaPin = String.fromEnvironment('PD_QA_LOCAL_PIN');
const pdLocalQaEntryEnabled = !kIsWeb &&
    bool.fromEnvironment('PD_INTERNAL_QA') && _localQaPin != '';

/// Cabin choice is navigation intent, never a server role grant.
class PdNativeCabinEntry extends StatefulWidget {
  const PdNativeCabinEntry({super.key, required this.signInBuilder,
    required this.identityApiBuilder,
    this.syncGatewayBuilder, this.enableMapTiles = true});
  final RemoteTripGateway Function(PdNativeSession session)? syncGatewayBuilder;
  final bool enableMapTiles;
  final PdSignInBuilder signInBuilder;
  final PdIdentityApi Function(PdNativeSession session) identityApiBuilder;
  @override
  State<PdNativeCabinEntry> createState() => _PdNativeCabinEntryState();
}

class _PdNativeCabinEntryState extends State<PdNativeCabinEntry> {
  String _page = 'entry';
  String _requestedRole = 'passenger';
  String? _message;
  PdNativeSession? _session;
  Timer? _expiry;
  bool _qaUnlocked = false;
  bool _testSyncStarted = false;
  bool _showTestSync = false;
  bool _localPilotOpened = false;
  bool _restoringQaSession = false;
  static const _qaSessionKey = 'pd_isolated_qa_session_v1';
  bool get _persistQaOnly => _serverSync &&
      const bool.fromEnvironment('PD_ISOLATED_QA_AUTH');

  @override
  void initState() {
    super.initState();
    if (_persistQaOnly) {
      _restoringQaSession = true;
      unawaited(_restoreQaSession());
    }
  }

  Future<void> _restoreQaSession() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final encoded = prefs.getString(_qaSessionKey);
      if (encoded == null) return;
      final data = jsonDecode(encoded);
      if (data is! Map<String, dynamic>) return;
      final token = data['token'];
      final user = data['user_id'];
      final role = data['role'];
      final expiryMs = data['expiry_ms'];
      if (token is! String || token.length < 40 ||
          user is! String || user.isEmpty ||
          !const {'passenger', 'pilot', 'dispatcher'}.contains(role) ||
          expiryMs is! int) {
        await prefs.remove(_qaSessionKey);
        return;
      }
      final session = PdNativeSession(
        token: token, userId: user, role: role as String,
        expiresAt: DateTime.fromMillisecondsSinceEpoch(expiryMs),
      );
      if (!session.active) {
        await prefs.remove(_qaSessionKey);
        return;
      }
      // Never trust locally stored roles; only the isolated server may affirm.
      final api = widget.syncGatewayBuilder!(session);
      try {
        final identity = await api.get('/v1/me');
        if (identity['role'] != session.role ||
            identity['actor'] != session.userId) {
          await prefs.remove(_qaSessionKey);
          return;
        }
      } on RemoteDemoException catch (error) {
        if (error.status == 401 || error.status == 403) {
          await prefs.remove(_qaSessionKey);
          if (mounted) _message = 'Тестовая сессия истекла. Войди ещё раз.';
        } else if (mounted) {
          _message = 'Тестовый сервер не ответил при восстановлении входа.';
        }
        return;
      } finally {
        api.close();
      }
      if (!mounted || _session != null || _page != 'entry') return;
      _requestedRole = session.role;
      _authenticated(session);
    } catch (_) {
      // Browser storage may be unavailable. Allow a new sign-in.
    } finally {
      if (mounted) setState(() => _restoringQaSession = false);
    }
  }

  Future<void> _clearQaSession() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_qaSessionKey);
    } catch (_) { /* QA-only best effort. */ }
  }

  Future<void> _saveQaSession(PdNativeSession session) async {
    if (!_persistQaOnly) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_qaSessionKey, jsonEncode({
        'token': session.token, 'user_id': session.userId,
        'role': session.role,
        'expiry_ms': session.expiresAt.millisecondsSinceEpoch,
      }));
    } catch (_) { /* QA browser storage is optional. */ }
  }
  PdNativeSession? get _activeSession => _session?.active == true ? _session : null;

  bool get _serverSync => widget.syncGatewayBuilder != null;
  bool get _localQa => pdLocalQaEntryEnabled && !_serverSync;
  bool get _internalGuest => !_serverSync && const bool.fromEnvironment('PD_INTERNAL_QA');

  bool _canOpen(PdNativeSession session, String role) => switch (role) {
    'pilot' => session.canPilot && (!_serverSync || session.role == 'pilot'),
    'dispatcher' => session.canDispatch,
    _ => !_serverSync || session.role == 'passenger',
  };

  void _openTestSync() {
    setState(() {
      _testSyncStarted = true;
      _showTestSync = true;
    });
  }

  void _entry() {
    Navigator.of(context).popUntil((route) => route.isFirst);
    setState(() { _page = 'entry'; _message = null; });
  }
  void _signOut() {
    if (_persistQaOnly) {
      unawaited(_clearQaSession());
    }
    _expiry?.cancel();
    _session = null;
    _qaUnlocked = false;
    _testSyncStarted = false;
    _showTestSync = false;
    _localPilotOpened = false;
    _entry();
  }
  void _select(String role) {
    if (_localQa) {
      if (_qaUnlocked) setState(() {
        _page = role;
        if (role == 'pilot') _localPilotOpened = true;
      });
      return;
    }
    setState(() {
      _requestedRole = role;
      _message = null;
      final session = _activeSession;
      if (role == 'pilot') {
        _page = 'photo';
      } else if (session != null) {
        _page = _canOpen(session, role) ? role : 'entry';
        if (_page == 'entry') _message = 'У аккаунта нет серверных прав для выбранного кабинета.';
      } else {
        _page = role == 'passenger' && _internalGuest ? role : 'signin';
      }
    });
  }
  void _authenticated(PdNativeSession session) {
    if (!mounted || !session.active) return;
    unawaited(_saveQaSession(session));
    _expiry?.cancel();
    _expiry = Timer(session.expiresAt.difference(DateTime.now()), () {
      if (mounted) _signOut();
    });
    setState(() {
      _session = session;
      if (_canOpen(session, _requestedRole)) {
        _page = _requestedRole == 'pilot' ? 'photo' : _requestedRole;
      } else {
        _page = 'entry';
        _message = 'У аккаунта нет серверных прав для выбранного кабинета.';
      }
    });
  }
  void _photoApproved() {
    final session = _activeSession;
    if (session == null || !_canOpen(session, 'pilot')) return;
    Navigator.of(context).popUntil((route) => route.isFirst);
    setState(() => _page = 'pilot');
  }
  void _photoSignIn() {
    Navigator.of(context).popUntil((route) => route.isFirst);
    setState(() { _requestedRole = 'pilot'; _page = 'signin'; });
  }
  @override
  void dispose() { _expiry?.cancel(); super.dispose(); }

  Widget _cabin(String role, PdNativeSession? session,
      {bool localQa = false, bool showPilotCockpit = true}) {
    final cabin = PrivateDriveDemo(
      key: ValueKey('entry-$role-${session?.userId ?? (localQa ? 'local-qa' : 'guest')}'),
      passengerOnly: role == 'passenger', pilotOnly: role == 'pilot',
      adminOnly: role == 'dispatcher', enableMapTiles: widget.enableMapTiles,
      syncGatewayBuilder: session != null && _serverSync
          ? () => widget.syncGatewayBuilder!(session) : null,
      syncRole: role,
      showPilotIdentityCheck: !localQa,
      showPilotCockpit: showPilotCockpit,
      storageScope: session?.userId ?? (localQa ? 'local-qa' : 'internal-guest'),
      onSignOut: _signOut, onBackToCabinets: _entry,
    );
    if (localQa) {
      return Scaffold(body: SafeArea(child: Column(children: [
        TextButton(
          key: const Key('local-qa-status'),
          onPressed: _openTestSync,
          child: const Text('Локальные данные · подключить диспетчерскую'),
        ),
        Expanded(child: cabin),
      ])));
    }
    Widget child = PdPermissionsFirstLaunch(child: cabin);
    if (session != null) {
      child = PdIdentityScope(api: widget.identityApiBuilder(session), child: child);
    } else {
      child = Scaffold(body: SafeArea(child: Column(children: [
        const Padding(padding: EdgeInsets.all(12), child: Text(
          'Гостевой доступ · внутренний тест. Телефон не подтверждён. '
          'Заказы сохраняются только на этом устройстве.',
          key: Key('internal-guest-status'), textAlign: TextAlign.center)),
        Expanded(child: child),
      ])));
    }
    return child;
  }

  @override
  Widget build(BuildContext context) {
    if (!_localQa || !_qaUnlocked || (!_testSyncStarted && !_localPilotOpened)) {
      return _buildCabin(context);
    }
    final showLocalPilot = _page == 'pilot' && !_showTestSync;
    return Stack(fit: StackFit.expand, children: [
      if (!_showTestSync && !showLocalPilot) _buildCabin(context),
      if (_localPilotOpened) Offstage(
        key: const Key('keep-local-pilot'),
        offstage: !showLocalPilot,
        child: TickerMode(
          enabled: showLocalPilot,
          child: PopScope(
            canPop: !showLocalPilot,
            onPopInvokedWithResult: (didPop, _) {
              if (!didPop && showLocalPilot) _entry();
            },
            child: _cabin('pilot', null, localQa: true,
              showPilotCockpit: showLocalPilot),
          ),
        ),
      ),
      if (_testSyncStarted) Offstage(
        key: const Key('keep-test-sync'),
        offstage: !_showTestSync,
        child: TickerMode(
          enabled: _showTestSync,
          child: PopScope(
            canPop: !_showTestSync,
            onPopInvokedWithResult: (didPop, _) {
              if (!didPop && _showTestSync) setState(() => _showTestSync = false);
            },
            child: RemoteSyncDemo(
              stagingDispatcher: true,
              onReturnHome: () => setState(() => _showTestSync = false),
            ),
          ),
        ),
      ),
    ]);
  }

  Widget _buildCabin(BuildContext context) {
    if (_restoringQaSession) {
      return const Scaffold(
        body: Center(child: Text('Проверяем сохранённый тестовый вход…')),
      );
    }
    if (_localQa) {
      if (!_qaUnlocked) {
        return _LocalQaSignIn(
          onUnlocked: () => setState(() => _qaUnlocked = true),
        );
      }
      if (_page == 'passenger') {
        return PopScope(
          canPop: false,
          onPopInvokedWithResult: (didPop, result) { if (!didPop) _entry(); },
          child: _cabin(_page, null, localQa: true),
        );
      }
    }
    final session = _activeSession;
    if (_page == 'signin') {
      return PopScope(canPop: false,
        onPopInvokedWithResult: (didPop, result) { if (!didPop) _entry(); },
        child: Scaffold(
          appBar: AppBar(title: Text(switch (_requestedRole) {
            'pilot' => 'Вход пилота', 'dispatcher' => 'Вход диспетчера',
            _ => 'Вход пассажира',
          }),
            leading: BackButton(onPressed: _entry)),
          body: widget.signInBuilder(context, _requestedRole, _authenticated),
        ),
      );
    }
    if (_page == 'photo') {
      return PopScope(canPop: false,
        onPopInvokedWithResult: (didPop, result) { if (!didPop) _entry(); },
        child: PdPilotIdentityNoticePage(
        api: session != null && _canOpen(session, 'pilot') ? widget.identityApiBuilder(session) : null,
        onBack: _entry,
        onRequestSignIn: _photoSignIn,
        onVerificationApproved: _photoApproved,
        onContinueWithoutVerification: _entry,
      ));
    }
    if (_page == 'passenger' && (session != null || _internalGuest)) {
      return _cabin('passenger', session);
    }
    if (session != null && (_page == 'pilot' || _page == 'dispatcher') &&
        _canOpen(session, _page)) return _cabin(_page, session);
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE'), actions: [
        if (session != null || _qaUnlocked) IconButton(onPressed: _signOut,
          icon: const Icon(Icons.logout), tooltip: 'Выйти'),
      ]),
      body: Stack(children: [
        const Positioned.fill(child: PrivateDriveBrightBackdrop()),
        SafeArea(child: Center(child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: ListView(shrinkWrap: true, padding: const EdgeInsets.all(24), children: [
            const PrivateDriveBrandLogo(size: 156, transparentBackground: true),
            const SizedBox(height: 16),
            const Text('Выбери кабинет', key: Key('entry-cabin-selection'),
              textAlign: TextAlign.center, style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
            const SizedBox(height: 20),
            FilledButton.icon(key: const Key('entry-passenger'),
              onPressed: () => _select('passenger'), icon: const Icon(Icons.person_outline),
              label: const Text('Пассажир')),
            const SizedBox(height: 12),
            FilledButton.icon(key: const Key('entry-pilot'),
              onPressed: () => _select('pilot'), icon: const Icon(Icons.directions_car_outlined),
              label: const Text('Пилот')),
            if (_serverSync) ...[
              const SizedBox(height: 12),
              FilledButton.icon(
                key: const Key('entry-dispatcher'),
                onPressed: () => _select('dispatcher'),
                icon: const Icon(Icons.support_agent),
                label: const Text('Диспетчер'),
              ),
            ],
            if (_localQa) ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                key: const Key('entry-staging-dispatch'),
                onPressed: _openTestSync,
                icon: const Icon(Icons.sync_alt),
                label: const Text('Тестовая связь с диспетчерской'),
              ),
            ],
            if (_message != null) Text(_message!, key: const Key('entry-role-message')),
            const SizedBox(height: 16),
            Text(_localQa
              ? 'Оба кабинета используют локальные тестовые данные.'
              : 'Фотопроверка требуется только пилоту. '
                'Доступ пилота подтверждается сервером.',
              textAlign: TextAlign.center),
            const SizedBox(height: 12),
            Text(_localQa
              ? String.fromEnvironment('PD_QA_BUILD_LABEL',
                defaultValue: 'Внутренняя сборка')
              : const String.fromEnvironment('PD_QA_BUILD_LABEL',
                   defaultValue: 'Версия 0.2.27 · сборка 2026112103'),
               key: const Key('app-demo-version'),
              textAlign: TextAlign.center, style: TextStyle(fontSize: 12)),
          ]),
        ))),
      ]),
    );
  }
}

/// A local development gate. The compiled PIN is a test fixture, never a
/// credential for a server account or a source of native roles.
class _LocalQaSignIn extends StatefulWidget {
  const _LocalQaSignIn({required this.onUnlocked});
  final VoidCallback onUnlocked;

  @override
  State<_LocalQaSignIn> createState() => _LocalQaSignInState();
}

class _LocalQaSignInState extends State<_LocalQaSignIn> {
  final _pin = TextEditingController();
  bool _showKeypad = false;
  String? _error;

  @override
  void dispose() {
    _pin.dispose();
    super.dispose();
  }

  void _toggleKeypad() {
    FocusScope.of(context).unfocus();
    setState(() => _showKeypad = !_showKeypad);
  }

  void _setPin(String value) {
    _pin.value = TextEditingValue(
      text: value,
      selection: TextSelection.collapsed(offset: value.length),
    );
    if (_error != null) setState(() => _error = null);
  }

  void _deleteDigit() {
    final value = _pin.text;
    if (value.isNotEmpty) _setPin(value.substring(0, value.length - 1));
  }

  Widget _digitButton(int digit) => OutlinedButton(
    key: ValueKey('local-qa-digit-$digit'),
    onPressed: () => _setPin('${_pin.text}$digit'),
    child: Text('$digit'),
  );

  Widget _keypadRow(List<Widget> buttons) => Row(
    children: [
      for (final button in buttons)
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            child: button,
          ),
        ),
    ],
  );

  void _submit() {
    if (_pin.text.trim() != _localQaPin) {
      setState(() => _error = 'Неверный тестовый пароль');
      return;
    }
    _pin.clear();
    FocusScope.of(context).unfocus();
    widget.onUnlocked();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE QA')),
    body: SafeArea(child: Center(child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 440),
      child: ListView(shrinkWrap: true, padding: const EdgeInsets.all(24), children: [
        const Center(child: PrivateDriveBrandLogo(size: 112, transparentBackground: true)),
        const SizedBox(height: 16),
        const Text('Тестовый вход', textAlign: TextAlign.center),
        const SizedBox(height: 16),
        Semantics(
          identifier: 'pd-qa-pin',
          child: TextField(
            key: const Key('local-qa-pin'),
            controller: _pin,
            obscureText: true,
            readOnly: _showKeypad,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _submit(),
            decoration: InputDecoration(labelText: 'Тестовый пароль', errorText: _error),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          key: const Key('local-qa-toggle-keypad'),
          onPressed: _toggleKeypad,
          child: Text(_showKeypad ? 'Системная клавиатура' : 'Ввести цифрами на экране'),
        ),
        if (_showKeypad) ...[
          for (var start = 1; start <= 7; start += 3)
            _keypadRow([
              _digitButton(start),
              _digitButton(start + 1),
              _digitButton(start + 2),
            ]),
          _keypadRow([
            const SizedBox.shrink(),
            _digitButton(0),
            OutlinedButton(
              key: const Key('local-qa-delete-digit'),
              onPressed: _deleteDigit,
              child: const Icon(Icons.backspace_outlined, semanticLabel: 'Стереть цифру'),
            ),
          ]),
        ],
        const SizedBox(height: 16),
        FilledButton(
          key: const Key('local-qa-enter'),
          onPressed: _submit,
          child: const Text('Войти в тест'),
        ),
        const Text('Вход открывает локальные тестовые кабинеты. '
          'Телефон и личность не подтверждаются.', textAlign: TextAlign.center),
      ]),
    ))),
  );
}
