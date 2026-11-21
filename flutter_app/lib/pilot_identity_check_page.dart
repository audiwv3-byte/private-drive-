import 'dart:typed_data';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'pilot_identity_api.dart';
import 'pilot_photo_capture.dart';

abstract class PdPilotCameraPermission {
  Future<bool> requestCamera();
}
class PdSystemPilotCameraPermission implements PdPilotCameraPermission {
  const PdSystemPilotCameraPermission();
  @override
  Future<bool> requestCamera() async =>
      !kIsWeb && (await Permission.camera.request()).isGranted;
}
class PdPilotIdentityCheckPage extends StatefulWidget {
  const PdPilotIdentityCheckPage({super.key,
    this.cameraPermission = const PdSystemPilotCameraPermission(),
    this.photoCapture = const PdSystemPilotPhotoCapture(),
    this.api, this.onContinueWithoutVerification, this.onRequestSignIn,
    this.onVerificationApproved});
  final PdPilotCameraPermission cameraPermission;
  final PdPilotPhotoCapture photoCapture;
  final PdIdentityApi? api;
  final VoidCallback? onContinueWithoutVerification;
  final VoidCallback? onRequestSignIn;
  final VoidCallback? onVerificationApproved;
  @override
  State<PdPilotIdentityCheckPage> createState() => _PdPilotIdentityCheckPageState();
}
class _PdPilotIdentityCheckPageState extends State<PdPilotIdentityCheckPage> {
  bool _busy = false;
  Uint8List? _photo;
  String _status = 'Проверка личности не выполнена';
  String? _message;
  PdIdentityApi? get _api => widget.api ?? PdIdentityScope.maybeOf(context);

  Future<void> _capture() async {
    if (_busy) return;
    setState(() { _busy = true; _message = null; });
    try {
      if (!await widget.cameraPermission.requestCamera()) {
        if (mounted) setState(() => _message =
            'Доступ к камере не предоставлен. Разреши камеру в настройках приложения и повтори.');
        return;
      }
      final photo = await widget.photoCapture.capture();
      if (!mounted) return;
      if (photo == null) {
        setState(() => _message = 'Съёмка отменена. Можно повторить или вернуться в кабинет.');
      } else if (photo.isEmpty || photo.length > 2 * 1024 * 1024) {
        setState(() => _message = 'Не удалось подготовить фото. Максимальный размер — 2 МБ. Повтори съёмку.');
      } else {
        setState(() { _photo = photo; _message = 'Проверь фото перед отправкой.'; });
      }
    } catch (_) {
      if (mounted) setState(() => _message =
          'Не удалось открыть камеру. Проверь разрешения и повтори съёмку.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
  Future<void> _submit() async {
    final api = _api;
    final photo = _photo;
    if (_busy || photo == null || api == null) return;
    setState(() { _busy = true; _message = null; });
    try {
      final result = await api.submit(photo);
      if (result['status'] != 'pending') {
        throw const FormatException('Expected pending review');
      }
      if (mounted) setState(() {
        _photo = null;
        _status = 'Фото отправлено · ожидает проверки диспетчером';
        _message = 'Отправка фото не подтверждает личность и не меняет права аккаунта.';
      });
    } catch (_) {
      if (mounted) setState(() => _message =
          'Фото не отправлено. Проверь подключение и повтори. Снимок оставлен для повторной отправки.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
  Future<void> _refresh() async {
    final api = _api;
    if (_busy || api == null) return;
    setState(() { _busy = true; _message = null; });
    try {
      final result = await api.status();
      final label = switch (result['status']) {
        'approved' => 'Личность подтверждена диспетчером',
        'pending' => 'Фото ожидает проверки диспетчером',
        'rejected' => 'Фото отклонено · сделай новый снимок',
        'expired' => 'Срок проверки истёк · сделай новый снимок',
        _ => 'Проверка личности не выполнена',
      };
      if (mounted) setState(() => _status = label);
      if (mounted && result['status'] == 'approved') widget.onVerificationApproved?.call();
    } catch (_) {
      if (mounted) setState(() => _message =
          'Не удалось получить статус с сервера. Повтори запрос.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE · Фотоконтроль')),
    body: SafeArea(child: ListView(
      key: const Key('pilot-identity-check-page'),
      padding: const EdgeInsets.all(24),
      children: [
        const Text('Подтверждение личности пилота',
            style: TextStyle(fontSize: 23, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        Text(_status, key: const Key('pilot-identity-unverified-status')),
        const SizedBox(height: 12),
        const Text('Сделай чёткий снимок лица при хорошем освещении. '
          'Фото отправляется только по отдельному нажатию. '
          'Решение принимает диспетчер; автоматического распознавания нет.',
          key: Key('pilot-identity-privacy')),
        if (const bool.fromEnvironment('PD_INTERNAL_QA') &&
            widget.onContinueWithoutVerification != null) ...[
          const SizedBox(height: 12),
          OutlinedButton.icon(
            key: const Key('pilot-identity-qa-skip'),
            onPressed: _busy ? null : widget.onContinueWithoutVerification,
            icon: const Icon(Icons.arrow_forward),
            label: const Text('Продолжить без проверки лица')),
          const Text('Только внутренняя тестовая сборка. Личность не подтверждена. Права не изменяются.'),
        ],
        const SizedBox(height: 16),
        if (_photo != null) ...[
          Image.memory(_photo!, height: 240, fit: BoxFit.contain,
            key: const Key('pilot-identity-photo-preview'),
            errorBuilder: (_, _, _) => const Text('Не удалось показать снимок. Сделай новое фото.')),
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('pilot-identity-submit'),
            onPressed: _busy || _api == null ? null : _submit,
            icon: const Icon(Icons.upload_outlined),
            label: const Text('Отправить на проверку')),
        ],
        FilledButton.icon(
          key: const Key('pilot-identity-request-camera'),
          onPressed: _busy ? null : _capture,
          icon: const Icon(Icons.camera_alt_outlined),
          label: Text(_photo == null ? 'Сделать фото' : 'Переснять')),
        if (_api == null) ...[
          Text(widget.onRequestSignIn == null
            ? 'Сервер фотоконтроля не подключён. Отправка недоступна; личность не подтверждена.'
            : 'Для отправки фото и доступа к кабинету пилота войди в аккаунт с серверными правами. '
              'Съёмка сама по себе не подтверждает личность.'),
          if (widget.onRequestSignIn != null)
            OutlinedButton(key: const Key('pilot-photo-sign-in'),
              onPressed: _busy ? null : widget.onRequestSignIn,
              child: const Text('Войти для отправки фото')),
        ],
        if (_message != null)
          Text(_message!, key: const Key('pilot-identity-result')),
        if (_busy) const LinearProgressIndicator(),
        const SizedBox(height: 12),
        OutlinedButton(
          key: const Key('pilot-identity-refresh'),
          onPressed: _busy || _api == null ? null : _refresh,
          child: const Text('Обновить статус')),
        TextButton(
          key: const Key('pilot-identity-back'),
          onPressed: _busy ? null : () => Navigator.of(context).maybePop(),
          child: const Text('Вернуться в кабинет')),
      ],
    )),
  );
}

