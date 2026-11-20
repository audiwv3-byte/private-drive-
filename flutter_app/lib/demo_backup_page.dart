import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'demo_backup.dart';

/// Manually invoked only from the offline DEMO entry point. Never installed
/// into production passenger/admin flows. The user explicitly controls copy,
/// import and confirmation. No data is sent to a server.
class DemoBackupPage extends StatefulWidget {
  const DemoBackupPage({super.key, this.repository});
  final DemoBackupRepository? repository;

  @override
  State<DemoBackupPage> createState() => _DemoBackupPageState();
}

class _DemoBackupPageState extends State<DemoBackupPage> {
  late final DemoBackupRepository _repository =
      widget.repository ?? DemoBackupRepository(DeviceDemoBackupPreferences());
  final TextEditingController _importController = TextEditingController();
  String? _exportText;
  String _message = '';
  bool _busy = false;

  @override
  void dispose() {
    _importController.dispose();
    super.dispose();
  }

  Future<void> _export() async {
    if (_busy) return;
    setState(() { _busy = true; _message = ''; });
    try {
      final text = await _repository.export();
      if (!mounted) return;
      setState(() {
        _exportText = text;
        _message = 'Копия проверена. Сохрани текст в безопасном месте.';
      });
    } catch (error) {
      if (mounted) setState(() =>
          _message = 'Экспорт не выполнен: ${error.runtimeType}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy() async {
    final text = _exportText;
    if (text == null || _busy) return;
    await Clipboard.setData(ClipboardData(text: text));
    if (mounted) setState(() =>
        _message = 'Скопировано. Не публикуй копию и не отправляй её в чат.');
  }

  Future<void> _import() async {
    if (_busy) return;
    final source = _importController.text.trim();
    DemoBackupSnapshot snapshot;
    try {
      snapshot = DemoBackupCodec.decode(source);
    } on FormatException catch (error) {
      setState(() => _message = 'Отказано: ${error.message}');
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Восстановить DEMO?'),
        content: Text(
          'Проверена версия и SHA-256. '
          'Перезаписать локальные тестовые заказы и переписки '
          '${snapshot.order == null ? "(копия без заказа)" : "(копия с заказом)"} '
          'и настройки? Сделай экспорт текущих данных заранее. '
          'Это не затронет продакшн, но отменить действие нельзя.',
        ),
        actions: [
          TextButton(
            key: const Key('demo-backup-cancel-restore'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            key: const Key('demo-backup-confirm-restore'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Восстановить'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() { _busy = true; _message = ''; });
    try {
      await _repository.restore(source);
      if (mounted) {
        setState(() {
          _message = 'Данные восстановлены. Закрой и заново открой '
              'офлайн DEMO, чтобы загрузились новые настройки и заказ.';
          _exportText = null; // An earlier export is now stale.
          _importController.clear();
        });
      }
    } catch (error) {
      if (mounted) setState(() =>
          _message = 'Восстановление отменено: ${error.toString()}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Резервная копия · DEMO')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text(
          'Только локальные тестовые заказы, сообщения и настройки. '
          'Никаких SMS-токенов, GPS или платёжных реквизитов. '
          'Копия не зашифрована: не копируй сюда настоящие адреса '
          'и не отправляй экспорт публично.',
          key: Key('demo-backup-privacy-warning'),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          key: const Key('demo-backup-export'),
          onPressed: _busy ? null : _export,
          icon: const Icon(Icons.file_download_outlined),
          label: const Text('Подготовить резервную копию'),
        ),
        if (_exportText != null) ...[
          const SizedBox(height: 12),
          TextField(
            key: const Key('demo-backup-export-data'),
            controller: TextEditingController(text: _exportText),
            readOnly: true,
            maxLines: 3,
            decoration: const InputDecoration(
              labelText: 'JSON · версия 1 · SHA-256',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('demo-backup-copy'),
            onPressed: _busy ? null : _copy,
            icon: const Icon(Icons.copy),
            label: const Text('Копировать копию'),
          ),
        ],
        const SizedBox(height: 28),
        const Text('Восстановление из сохранённого JSON'),
        const SizedBox(height: 8),
        TextField(
          key: const Key('demo-backup-import-data'),
          controller: _importController,
          maxLines: 4,
          decoration: const InputDecoration(
            border: OutlineInputBorder(),
            hintText: 'Вставь резервную копию сюда',
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const Key('demo-backup-restore'),
          onPressed: _busy ? null : _import,
          icon: const Icon(Icons.settings_backup_restore),
          label: const Text('Проверить и восстановить'),
        ),
        if (_busy) const LinearProgressIndicator(),
        if (_message.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(_message, key: const Key('demo-backup-message')),
          ),
      ],
    ),
  );
}
