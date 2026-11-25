import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'brand_logo.dart';
import 'app_language.dart' show pdLabel;
import 'company_info.dart' show openPrivateDriveLink;
import 'private_drive_bright_backdrop.dart';
import 'demo_interfaces.dart';
import 'permissions_onboarding.dart';
import 'native_session.dart';
import 'pilot_identity_api.dart';
import 'pilot_identity_notice_page.dart';
import 'remote_sync_demo.dart';

typedef PdSignInBuilder = Widget Function(BuildContext context, String role,
    ValueChanged<PdNativeSession> onAuthenticated);

const _localQaPin = String.fromEnvironment('PD_QA_LOCAL_PIN');
const pdLocalQaEntryEnabled = !kIsWeb &&
    bool.fromEnvironment('PD_INTERNAL_QA') && _localQaPin != '';

/// Cabin choice is navigation intent, never a server role grant.
class PdNativeCabinEntry extends StatefulWidget {
  const PdNativeCabinEntry({super.key, required this.signInBuilder,
    required this.identityApiBuilder});
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
  PdNativeSession? get _activeSession => _session?.active == true ? _session : null;

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
    _expiry?.cancel();
    _session = null;
    _qaUnlocked = false;
    _testSyncStarted = false;
    _showTestSync = false;
    _localPilotOpened = false;
    _entry();
  }
  void _select(String role) {
    if (pdLocalQaEntryEnabled) {
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
      } else {
        _page = session != null || const bool.fromEnvironment('PD_INTERNAL_QA')
            ? 'passenger' : 'signin';
      }
    });
  }
  void _authenticated(PdNativeSession session) {
    if (!mounted || !session.active) return;
    _expiry?.cancel();
    _expiry = Timer(session.expiresAt.difference(DateTime.now()), () {
      if (mounted) _signOut();
    });
    setState(() {
      _session = session;
      if (_requestedRole == 'pilot' && session.canPilot) {
        _page = 'photo';
      } else if (_requestedRole == 'passenger') {
        _page = 'passenger';
      } else {
        _page = 'entry';
        _message = 'У аккаунта нет серверных прав для выбранного кабинета.';
      }
    });
  }
  void _photoApproved() {
    if (_activeSession?.canPilot != true) return;
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
    if (!pdLocalQaEntryEnabled || !_qaUnlocked || (!_testSyncStarted && !_localPilotOpened)) {
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
    if (pdLocalQaEntryEnabled) {
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
          appBar: AppBar(title: Text(_requestedRole == 'pilot' ? 'Вход пилота' : 'Вход пассажира'),
            leading: BackButton(onPressed: _entry)),
          body: widget.signInBuilder(context, _requestedRole, _authenticated),
        ),
      );
    }
    if (_page == 'photo') {
      return PopScope(canPop: false,
        onPopInvokedWithResult: (didPop, result) { if (!didPop) _entry(); },
        child: PdPilotIdentityNoticePage(
        api: session != null && session.canPilot ? widget.identityApiBuilder(session) : null,
        onBack: _entry,
        onRequestSignIn: _photoSignIn,
        onVerificationApproved: _photoApproved,
        onContinueWithoutVerification: _entry,
      ));
    }
    if (_page == 'passenger' && (session != null || const bool.fromEnvironment('PD_INTERNAL_QA'))) {
      return _cabin('passenger', session);
    }
    if (_page == 'pilot' && session?.canPilot == true) return _cabin('pilot', session);
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
            const SizedBox(height: 12),
            OutlinedButton(
              key: const Key('entry-apply-pilot'),
              onPressed: () => openPrivateDriveLink(
                context,
                Uri.https('wilsonpark.pythonanywhere.com', '/pilot-registration'),
              ),
              child: Text(pdLabel(context, 'Стать пилотом')),
            ),
            if (pdLocalQaEntryEnabled) ...[
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
            const Text(pdLocalQaEntryEnabled
              ? 'Оба кабинета используют локальные тестовые данные.'
              : 'Фотопроверка требуется только пилоту. '
                'Доступ пилота подтверждается сервером.',
              textAlign: TextAlign.center),
            const SizedBox(height: 12),
            const Text(pdLocalQaEntryEnabled
              ? String.fromEnvironment('PD_QA_BUILD_LABEL',
                defaultValue: 'Внутренняя сборка')
              : 'Версия 0.2.27 · сборка 2026112103', key: Key('app-demo-version'),
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
