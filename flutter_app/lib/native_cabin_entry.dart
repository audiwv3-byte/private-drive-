import 'dart:async';
import 'package:flutter/material.dart';
import 'brand_logo.dart';
import 'private_drive_bright_backdrop.dart';
import 'demo_interfaces.dart';
import 'permissions_onboarding.dart';
import 'native_session.dart';
import 'native_logout_api.dart';
import 'native_session_manager.dart';
import 'pilot_identity_api.dart';
import 'pilot_identity_notice_page.dart';

typedef PdSignInBuilder = Widget Function(BuildContext context, String role,
    ValueChanged<PdNativeSession> onAuthenticated);

/// Cabin choice is navigation intent, never a server role grant.
class PdNativeCabinEntry extends StatefulWidget {
  const PdNativeCabinEntry({super.key, required this.signInBuilder,
    required this.identityApiBuilder, this.logoutApi, this.sessionManager});
  final PdSignInBuilder signInBuilder;
  final PdIdentityApi Function(PdNativeSession session) identityApiBuilder;
  final PdNativeLogoutApi? logoutApi;
  final PdNativeSessionManager? sessionManager;
  @override
  State<PdNativeCabinEntry> createState() => _PdNativeCabinEntryState();
}

class _PdNativeCabinEntryState extends State<PdNativeCabinEntry> {
  String _page = 'entry';
  String _requestedRole = 'passenger';
  String? _message;
  PdNativeSession? _session;
  Timer? _expiry;
  bool _loggingOut = false;
  bool _restoring = false;
  Future<void>? _pendingSessionSave;
  PdNativeSession? get _activeSession => _session?.active == true ? _session : null;
  @override
  void initState() {
    super.initState();
    if (widget.sessionManager != null) {
      _restoreSavedSession();
    }
  }

  Future<void> _restoreSavedSession() async {
    setState(() => _restoring = true);
    try {
      final restored = await widget.sessionManager!.restore();
      if (!mounted || restored == null || _session != null) return;
      _authenticated(restored, persist: false, restored: true);
    } catch (_) {
      // No session or role is granted until the server validates the token.
    } finally {
      if (mounted) setState(() => _restoring = false);
    }
  }


  void _entry() {
    Navigator.of(context).popUntil((route) => route.isFirst);
    setState(() { _page = 'entry'; _message = null; });
  }
  void _clearExpiredSession() {
    _expiry?.cancel();
    _session = null;
    _entry();
  }

  Future<void> _signOut() async {
    if (_loggingOut) return;
    final session = _activeSession;
    if (session == null) {
      _clearExpiredSession();
      return;
    }
    final api = widget.logoutApi;
    if (api == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Выход с сервера пока недоступен. Сессия сохранена.')));
      return;
    }
    setState(() => _loggingOut = true);
    try {
      await api.revokeCurrentDevice(session.token);
      // A confirmed server logout is the only path that removes the stored
      // credential. If secure-storage deletion fails, retain fail-closed UI.
      if (widget.sessionManager != null) {
        // A delayed secure-storage write must never resurrect a token after
        // the server has revoked that same session.
        await _pendingSessionSave;
        await widget.sessionManager!.forgetConfirmedSession(session.token);
      }
      if (!mounted || !identical(_session, session)) return;
      _clearExpiredSession();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Не удалось завершить сеанс на сервере. Повтори позже.')));
    } finally {
      if (mounted) setState(() => _loggingOut = false);
    }
  }
  void _select(String role) {
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
  void _authenticated(PdNativeSession session, {
    bool persist = true, bool restored = false,
  }) {
    if (!mounted || !session.active) return;
    if (persist && widget.sessionManager != null) {
      // Persist only OTP-verified sessions received from the existing
      // authenticated callback; no guest mode or role picker can write tokens.
      _pendingSessionSave =
          widget.sessionManager!.remember(session).catchError((_) {});
    }
    _expiry?.cancel();
    _expiry = Timer(session.expiresAt.difference(DateTime.now()), () {
      if (mounted) _clearExpiredSession();
    });
    setState(() {
      _session = session;
      // After a cold start, never auto-enter a previously chosen staff cabin.
      // Require explicit cabin selection from freshly verified server rights.
      if (restored) {
        _page = 'entry';
      } else if (_requestedRole == 'pilot' && session.canPilot) {
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

  Widget _cabin(String role, PdNativeSession? session) {
    final cabin = PrivateDriveDemo(
      key: ValueKey('entry-$role-${session?.userId ?? 'guest'}'),
      passengerOnly: role == 'passenger', pilotOnly: role == 'pilot',
      adminOnly: role == 'dispatcher',
      storageScope: session?.userId ?? 'internal-guest',
      onSignOut: _signOut, onBackToCabinets: _entry,
    );
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
    if (_restoring) {
      return const Scaffold(body: Center(
        child: CircularProgressIndicator(key: Key('native-session-restoring'))));
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
        if (session != null) IconButton(onPressed: _loggingOut ? null : _signOut,
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
            const Text('Фотопроверка требуется только пилоту. '
              'Доступ пилота и диспетчера подтверждается сервером.', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            const Text('Версия 0.2.27 · сборка 2026112103', key: Key('app-demo-version'),
              textAlign: TextAlign.center, style: TextStyle(fontSize: 12)),
          ]),
        ))),
      ]),
    );
  }
}
