import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

/// Narrow, replaceable interface: the preview NEVER captures, stores or sends
/// a photo, uses biometrics or changes driver eligibility.
abstract class PdPilotCameraPermission {
  Future<bool> requestCamera();
}

class PdSystemPilotCameraPermission implements PdPilotCameraPermission {
  const PdSystemPilotCameraPermission();

  @override
  Future<bool> requestCamera() async {
    if (kIsWeb) return false; // Web permission needs a separate user-media flow.
    final status = await Permission.camera.request();
    return status.isGranted;
  }
}

/// Identity-check UX proposal only: no camera preview, photos or verification.
/// The non-verifying QA bypass is compiled only into explicitly flagged builds.
class PdPilotIdentityCheckPage extends StatefulWidget {
  const PdPilotIdentityCheckPage({
    super.key,
    this.cameraPermission = const PdSystemPilotCameraPermission(),
    this.onContinueWithoutVerification,
  });

  final PdPilotCameraPermission cameraPermission;
  final VoidCallback? onContinueWithoutVerification;

  @override
  State<PdPilotIdentityCheckPage> createState() =>
      _PdPilotIdentityCheckPageState();
}

class _PdPilotIdentityCheckPageState extends State<PdPilotIdentityCheckPage> {
  bool _requesting = false;
  String? _result;

  Future<void> _start() async {
    if (_requesting) return;
    setState(() {
      _requesting = true;
      _result = null;
    });
    try {
      final allowed = await widget.cameraPermission.requestCamera();
      if (!mounted) return;
      setState(() {
        _result = allowed
            ? 'Камера разрешена. Съёмка отключена: '
              'проверка личности ещё не подключена.'
            : 'Доступ к камере не предоставлен. '
              'Разрешение можно изменить в настройках устройства.';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _result = 'Не удалось запросить камеру. '
            'Проверь разрешения приложения в настройках устройства.';
      });
    } finally {
      if (mounted) setState(() => _requesting = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('PRIVATE DRIVE · Проверка личности')),
        body: SafeArea(
          child: ListView(
            key: const Key('pilot-identity-check-page'),
            padding: const EdgeInsets.all(24),
            children: [
              const Icon(Icons.verified_user_outlined,
                  size: 72, color: Color(0xFFDDC184)),
              const SizedBox(height: 18),
              const Text('Подтверждение личности пилота',
                  style: TextStyle(fontSize: 23, fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              const Text(
                'Планируемая проверка: при первом подключении, затем '
                'не реже одного раза в 7 дней. Сейчас это тестовый экран. '
                'Он не может подтвердить личность и не влияет на доступ к заказам.',
                key: Key('pilot-identity-explanation'),
              ),
              const SizedBox(height: 14),
              const Text(
                'Для будущего подтверждения личности потребуется камера. '
                'Разрешение запрашивается только после нажатия кнопки. '
                'Фотография не создаётся, не сохраняется и не отправляется. '
                'Биометрическое распознавание отсутствует. '
                'Микрофон для проверки лица не используется.',
                key: Key('pilot-identity-privacy'),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                key: const Key('pilot-identity-request-camera'),
                onPressed: _requesting ? null : _start,
                icon: const Icon(Icons.camera_alt_outlined),
                label: Text(_requesting
                    ? 'Запрос разрешения…'
                    : 'Разрешить камеру для проверки'),
              ),
              if (_result != null) ...[
                const SizedBox(height: 16),
                Text(_result!, key: const Key('pilot-identity-result')),
              ],
              const SizedBox(height: 20),
              if (const bool.fromEnvironment('PD_INTERNAL_QA') &&
                  widget.onContinueWithoutVerification != null) ...[
                OutlinedButton.icon(
                  key: const Key('pilot-identity-qa-skip'),
                  onPressed: widget.onContinueWithoutVerification,
                  icon: const Icon(Icons.arrow_forward),
                  label: const Text('Продолжить без проверки лица'),
                ),
                const Text('Только внутренняя тестовая сборка. Личность не подтверждена. '
                    'Дополнительные права не выдаются.'),
                const SizedBox(height: 16),
              ],
              const Text(
                'Статус: проверка личности не выполнена. '
                'Реальный процесс будет доступен после защищённой '
                'серверной интеграции и утверждения обработки данных.',
                key: Key('pilot-identity-unverified-status'),
              ),
            ],
          ),
        ),
      );
}
