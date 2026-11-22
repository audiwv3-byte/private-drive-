import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'brand_logo.dart';
import 'private_drive_bright_backdrop.dart';
import 'demo_interfaces.dart';
import 'permissions_onboarding.dart';
import 'native_session.dart';
import 'pilot_identity_api.dart';
import 'pilot_identity_notice_page.dart';

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
  PdNativeSession? get _activeSession => _session?.active == true ? _session : null;

  void _entry() {
    Navigator.of(context).popUntil((route) => route.isFirst);
    setState(() { _page = 'entry'; _message = null; });
  }
  void _signOut() {
    _expiry?.cancel();
    _session = null;
    _qaUnlocked = false;
    _entry();
  }
  void _select(String role) {
    if (pdLocalQaEntryEnabled) {
      if (_qaUnlocked) setState(() => _page = role);
      return;
    }
    setState(() {
      _requestedRole = role;
      _message = null;
      final session = _activeSession;
      if (role == 'pilot') {
        _page = 'photo';
      } else if (role == 'dispatcher') {
        _page = session?.canDispatch == true ? 'dispatcher' : 'signin';
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
      } else if (_requestedRole == 'dispatcher' && session.canDispatch) {
        _page = 'dispatcher';
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

  Widget _cabin(String role, PdNativeSession? session, {bool localQa = false}) {
    final cabin = PrivateDriveDemo(
      key: ValueKey('entry-$role-${session?.userId ?? (localQa ? 'local-qa' : 'guest')}'),
      passengerOnly: role == 'passenger', pilotOnly: role == 'pilot',
      adminOnly: role == 'dispatcher',
      storageScope: session?.userId ?? (localQa ? 'local-qa' : 'internal-guest'),
      onSignOut: _signOut, onBackToCabinets: _entry,
    );
    if (localQa) {
      return Scaffold(body: SafeArea(child: Column(children: [
        const Padding(
          padding: EdgeInsets.all(8),
          child: Text('Внутренний тест · локальные данные',
            key: Key('local-qa-status'), textAlign: TextAlign.center),
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
    if (pdLocalQaEntryEnabled) {
      if (!_qaUnlocked) {
        return _LocalQaSignIn(
          onUnlocked: () => setState(() => _qaUnlocked = true),
        );
      }
      if (const {'passenger', 'pilot', 'dispatcher'}.contains(_page)) {
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
          appBar: AppBar(title: Text(_requestedRole == 'dispatcher'
              ? 'Вход диспетчера' : _requestedRole == 'pilot' ? 'Вход пилота' : 'Вход пассажира'),
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
    if (_page == 'dispatcher' && session?.canDispatch == true) return _cabin('dispatcher', session);
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
            FilledButton.icon(key: const Key('entry-dispatcher'),
              onPressed: () => _select('dispatcher'), icon: const Icon(Icons.support_agent_outlined),
              label: const Text('Диспетчер')),
            if (_message != null) Text(_message!, key: const Key('entry-role-message')),
            const SizedBox(height: 16),
            const Text(pdLocalQaEntryEnabled
              ? 'Все три кабинета работают с локальными тестовыми данными.'
              : 'Фотопроверка требуется только пилоту. '
                'Доступ пилота и диспетчера подтверждается сервером.',
              textAlign: TextAlign.center),
            const SizedBox(height: 12),
            const Text(pdLocalQaEntryEnabled
              ? 'Версия 0.2.28 · внутренняя сборка'
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
  String? _error;

  @override
  void dispose() {
    _pin.dispose();
    super.dispose();
  }

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
        TextField(
          key: const Key('local-qa-pin'),
          controller: _pin,
          obscureText: true,
          keyboardType: TextInputType.number,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _submit(),
          decoration: InputDecoration(labelText: 'Тестовый пароль', errorText: _error),
        ),
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
