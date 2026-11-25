import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'app_language.dart';

/// Only foreground location and notification permissions are requested.
/// No background location, SMS-reading or other sensitive permissions.
abstract class PdPermissionGateway {
  Future<PermissionStatus> notificationStatus();
  Future<PermissionStatus> locationStatus();
  Future<PermissionStatus> requestNotifications();
  Future<PermissionStatus> requestLocation();
  Future<bool> openSettings();
}

class AndroidPermissionGateway implements PdPermissionGateway {
  const AndroidPermissionGateway();

  @override
  Future<PermissionStatus> notificationStatus() =>
      Permission.notification.status;
  @override
  Future<PermissionStatus> locationStatus() =>
      Permission.locationWhenInUse.status;
  @override
  Future<PermissionStatus> requestNotifications() =>
      Permission.notification.request();
  @override
  Future<PermissionStatus> requestLocation() =>
      Permission.locationWhenInUse.request();
  @override
  Future<bool> openSettings() => openAppSettings();
}

const _permissionsSeenKey = 'pd_native_permissions_onboarding_v1';

Future<bool> _readPermissionsSeen() async =>
    (await SharedPreferencesAsync().getBool(_permissionsSeenKey)) ?? false;

Future<void> _savePermissionsSeen() async =>
    SharedPreferencesAsync().setBool(_permissionsSeenKey, true);

class PdPermissionsFirstLaunch extends StatefulWidget {
  const PdPermissionsFirstLaunch({
    super.key,
    required this.child,
    this.gateway = const AndroidPermissionGateway(),
    this.readCompleted = _readPermissionsSeen,
    this.writeCompleted = _savePermissionsSeen,
  });

  final Widget child;
  final PdPermissionGateway gateway;
  final Future<bool> Function() readCompleted;
  final Future<void> Function() writeCompleted;

  @override
  State<PdPermissionsFirstLaunch> createState() => _PdPermissionsFirstLaunchState();
}

class _PdPermissionsFirstLaunchState extends State<PdPermissionsFirstLaunch> {
  bool? _completed;
  bool _busy = false;
  bool _requestFailed = false;

  @override
  void initState() {
    super.initState();
    // Browser permissions are managed by Safari at the point GPS is used.
    // Do not invoke Android's permission_handler prompts on Web.
    if (kIsWeb) {
      _completed = true;
    } else {
      _restore();
    }
  }

  Future<void> _restore() async {
    bool complete;
    try {
      complete = await widget.readCompleted();
    } catch (_) {
      // If local storage is unavailable, never block sign-in.
      complete = true;
    }
    if (mounted) setState(() => _completed = complete);
  }

  Future<void> _finish() async {
    try {
      await widget.writeCompleted();
    } catch (_) {
      // Permissions are optional even when device storage is unavailable.
    }
    if (mounted) setState(() {
      _completed = true;
      _busy = false;
    });
  }

  Future<void> _request() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _requestFailed = false;
    });
    try {
      // Two separate native prompts, always following a user tap.
      await widget.gateway.requestNotifications();
      await widget.gateway.requestLocation();
    } catch (_) {
      if (mounted) {
        setState(() => _requestFailed = true);
      }
    } finally {
      await _finish();
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_completed == true) return widget.child;
    if (_completed == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    String tr(String ru, String lt, String en) => pdEntryTr(context, ru, lt, en);
    return Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE')),
      body: SafeArea(
        child: Center(child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.all(24),
            children: [
              const Icon(Icons.admin_panel_settings_outlined,
                size: 66, color: Color(0xFFDDC184)),
              const SizedBox(height: 18),
              Text(tr('Разрешения приложения', 'Programėlės leidimai', 'App permissions'),
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              ListTile(
                leading: const Icon(Icons.notifications_active_outlined),
                title: Text(tr('Уведомления', 'Pranešimai', 'Notifications')),
                subtitle: Text(tr(
                  'Для сообщений пилота и изменений заказа после подключения уведомлений.',
                  'Vairuotojo žinutėms ir kelionės pakeitimams, kai pranešimai įjungti.',
                  'For driver messages and booking updates when notifications are enabled.')),
              ),
              ListTile(
                leading: const Icon(Icons.my_location_outlined),
                title: Text(tr('Местоположение', 'Vieta', 'Location')),
                subtitle: Text(tr(
                  'Для определения точки посадки на карте. Только при использовании приложения.',
                  'Paėmimo vietai žemėlapyje nustatyti, tik naudojantis programėle.',
                  'To locate your pickup point on the map, only while using the app.')),
              ),
              const SizedBox(height: 16),
              if (_requestFailed) Text(tr(
                'Не удалось запросить разрешения. Можно включить их в настройках приложения.',
                'Nepavyko paprašyti leidimų. Juos gali įjungti programėlės nustatymuose.',
                'Could not request permissions. You can enable them in the app settings.'),
                key: const Key('permission-onboarding-error')),
              FilledButton(
                key: const Key('permission-onboarding-allow'),
                onPressed: _busy ? null : _request,
                child: Text(tr('Разрешить', 'Leisti', 'Allow')),
              ),
              TextButton(
                key: const Key('permission-onboarding-skip'),
                onPressed: _busy ? null : _finish,
                child: Text(tr('Продолжить без разрешений', 'Tęsti be leidimų',
                  'Continue without permissions')),
              ),
              Text(tr('Отказ не блокирует вход. Разрешения можно '
                  'включить позднее в настройках PRIVATE DRIVE.',
                'Prisijungti gali ir be leidimų. Vėliau juos gali įjungti PRIVATE DRIVE nustatymuose.',
                'You can sign in without permissions and enable them later in PRIVATE DRIVE settings.'),
                textAlign: TextAlign.center),
            ],
          ),
        )),
      ),
    );
  }
}

class PdPermissionSettingsPage extends StatefulWidget {
  const PdPermissionSettingsPage({
    super.key,
    this.gateway = const AndroidPermissionGateway(),
  });
  final PdPermissionGateway gateway;

  @override
  State<PdPermissionSettingsPage> createState() => _PdPermissionSettingsPageState();
}

class _PdPermissionSettingsPageState extends State<PdPermissionSettingsPage>
    with WidgetsBindingObserver {
  PermissionStatus? _notifications;
  PermissionStatus? _location;
  bool _working = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    try {
      final notification = await widget.gateway.notificationStatus();
      final location = await widget.gateway.locationStatus();
      if (!mounted) return;
      setState(() {
        _notifications = notification;
        _location = location;
      });
    } catch (_) {
      // On unsupported platforms the app still opens and offers Settings.
    }
  }

  Future<void> _request(bool notification) async {
    if (_working) return;
    setState(() => _working = true);
    try {
      final status = notification ? _notifications : _location;
      if (status?.isPermanentlyDenied == true || status?.isRestricted == true) {
        await widget.gateway.openSettings();
      } else {
        if (notification) {
          await widget.gateway.requestNotifications();
        } else {
          await widget.gateway.requestLocation();
        }
      }
    } catch (_) {
      // Android can restrict individual prompts; system settings remain available.
    } finally {
      await _refresh();
      if (mounted) setState(() => _working = false);
    }
  }

  String _status(PermissionStatus? status) {
    if (status == null) return 'Проверка разрешения…';
    if (status.isGranted || status.isLimited || status.isProvisional) {
      return 'Разрешено';
    }
    if (status.isPermanentlyDenied || status.isRestricted) {
      return 'Отключено · включи в настройках Android';
    }
    return 'Не разрешено';
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Разрешения PRIVATE DRIVE')),
    body: SafeArea(child: ListView(padding: const EdgeInsets.all(16),
      children: [
        ListTile(
          key: const Key('permission-settings-notifications'),
          leading: const Icon(Icons.notifications_outlined),
          title: const Text('Уведомления'),
          subtitle: Text(_status(_notifications)),
          trailing: OutlinedButton(
            onPressed: _working ? null : () => _request(true),
            child: const Text('Настроить'),
          ),
        ),
        ListTile(
          key: const Key('permission-settings-location'),
          leading: const Icon(Icons.my_location),
          title: const Text('Местоположение'),
          subtitle: Text(_status(_location)),
          trailing: OutlinedButton(
            onPressed: _working ? null : () => _request(false),
            child: const Text('Настроить'),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          key: const Key('permission-open-system-settings'),
          onPressed: widget.gateway.openSettings,
          icon: const Icon(Icons.settings_outlined),
          label: const Text('Открыть настройки Android'),
        ),
        const Text('Можно продолжать пользоваться приложением без разрешений. '
          'После возврата из настроек состояние обновится.'),
      ],
    )),
  );
}
