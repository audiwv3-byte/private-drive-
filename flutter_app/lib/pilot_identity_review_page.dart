import 'dart:convert';
import 'package:flutter/material.dart';
import 'pilot_identity_api.dart';

class PdIdentityReviewPage extends StatefulWidget {
  const PdIdentityReviewPage({super.key, required this.api});
  final PdIdentityApi api;
  @override
  State<PdIdentityReviewPage> createState() => _PdIdentityReviewPageState();
}

class _PdIdentityReviewPageState extends State<PdIdentityReviewPage> {
  List<dynamic> _items = [];
  List<dynamic> _pilots = [];
  bool _busy = false;
  String _message = '';
  @override
  void initState() { super.initState(); _load(); }
  Future<void> _load() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final results = await Future.wait([
        widget.api.request('GET', 'queue'),
        widget.api.request('GET', 'pilots'),
      ]);
      if (mounted) setState(() {
        _items = results[0]['items'] as List<dynamic>;
        _pilots = results[1]['items'] as List<dynamic>;
        _message = _items.isEmpty ? 'Нет фотографий на проверке' : '';
      });
    } catch (_) {
      if (mounted) setState(() => _message = 'Не удалось получить очередь. Проверь права и подключение.');
    } finally { if (mounted) setState(() => _busy = false); }
  }
  Future<void> _send(String endpoint, Map<String, dynamic> payload) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await widget.api.request('POST', endpoint, payload);
    } catch (_) {
      if (mounted) setState(() => _message = 'Не удалось сохранить настройку фотопроверки.');
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (mounted) await _load();
  }

  Future<void> _editSchedule(Map<String, dynamic> pilot) async {
    var days = pilot['interval_days'] as int? ?? 7;
    final now = DateTime.now();
    final lastDate = now.add(const Duration(days: 365));
    final currentDue = pilot['next_due_at'] as int?;
    var due = currentDue == null ? now.add(Duration(days: days)) :
        DateTime.fromMillisecondsSinceEpoch(currentDue * 1000);
    if (due.isBefore(now)) due = now.add(const Duration(hours: 1));
    final settings = await showDialog<Map<String, dynamic>>(context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('График фотопроверки'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              const Expanded(child: Text('Повторять каждые')),
              DropdownButton<int>(
                value: days,
                items: [
                  for (var day = 1; day <= 30; day++)
                    DropdownMenuItem(value: day, child: Text('$day дн.')),
                ],
                onChanged: (value) => setDialogState(() => days = value ?? days),
              ),
            ]),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Первая проверка'),
              subtitle: Text(_formatDate(context, due)),
              onTap: () async {
                final date = await showDatePicker(
                  context: context, initialDate: due.isAfter(lastDate) ? lastDate : due,
                  firstDate: now, lastDate: lastDate,
                );
                if (date == null || !context.mounted) return;
                final time = await showTimePicker(
                  context: context, initialTime: TimeOfDay.fromDateTime(due),
                );
                if (time == null || !context.mounted) return;
                setDialogState(() =>
                  due = DateTime(date.year, date.month, date.day, time.hour, time.minute));
              },
            ),
          ]),
          actions: [
            if (currentDue != null)
              TextButton(
                onPressed: () => Navigator.pop(dialogContext,
                  {'interval_days': null, 'next_due_at': null}),
                child: const Text('Отключить график'),
              ),
            TextButton(onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Отмена')),
            FilledButton(
              onPressed: due.isBefore(DateTime.now()) ? null : () =>
                Navigator.pop(dialogContext, {
                  'interval_days': days,
                  'next_due_at': due.millisecondsSinceEpoch ~/ 1000,
                }),
              child: const Text('Сохранить'),
            ),
          ],
        ),
      ),
    );
    if (settings != null && mounted) {
      await _send('schedule', {'user_id': pilot['user_id'], ...settings});
    }
  }

  String _formatDate(BuildContext context, DateTime date) {
    final locale = MaterialLocalizations.of(context);
    return '${locale.formatCompactDate(date)} ${TimeOfDay.fromDateTime(date).format(context)}';
  }

  Future<void> _review(String id) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final result = await widget.api.request('GET', 'photo/$id');
      final bytes = base64Decode(result['photo'] as String);
      if (!mounted) return;
      final decision = await showDialog<String>(context: context,
        builder: (context) => AlertDialog(
          title: const Text('Проверка личности пилота'),
          content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min,
            children: [Image.memory(bytes, height: 260),
              const Text('Подтверждай только после сравнения с ранее проверенными данными пилота. '
                'Снимок будет удалён после решения. Права аккаунта не изменятся.')],
          )),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('Закрыть')),
            TextButton(onPressed: () => Navigator.pop(context, 'rejected'), child: const Text('Отклонить')),
            FilledButton(onPressed: () => Navigator.pop(context, 'approved'), child: const Text('Подтвердить')),
          ],
        ));
      if (decision == null) return;
      await widget.api.request('POST', 'decision/$id', {'decision': decision});
      if (mounted) setState(() => _items.removeWhere((item) => item['id'] == id));
    } catch (_) {
      if (mounted) setState(() => _message = 'Решение не сохранено. Обнови очередь и повтори.');
    } finally { if (mounted) setState(() => _busy = false); }
  }
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE · Фотоконтроль пилотов')),
    body: SafeArea(child: ListView(padding: const EdgeInsets.all(16), children: [
      if (_busy) const LinearProgressIndicator(),
      if (_message.isNotEmpty) Text(_message),
      OutlinedButton(onPressed: _busy ? null : _load, child: const Text('Обновить очередь')),
      for (final pilot in _pilots.cast<Map<String, dynamic>>())
        Card(child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Пилот: ${pilot['user_id']}'),
            if (pilot['next_due_at'] case final int due)
              Text('Следующая проверка: ${_formatDate(context,
                DateTime.fromMillisecondsSinceEpoch(due * 1000))}'),
            if (pilot['requested'] == true) const Text('Проверка запрошена'),
            Wrap(spacing: 8, children: [
              OutlinedButton(
                onPressed: _busy || pilot['requested'] == true ? null : () =>
                  _send('request', {'user_id': pilot['user_id']}),
                child: const Text('Запросить фото'),
              ),
              OutlinedButton(
                onPressed: _busy ? null : () => _editSchedule(pilot),
                child: const Text('Настроить график'),
              ),
            ]),
          ]),
        )),
      for (final item in _items) ListTile(
        title: Text('Пилот: ${item['user_id']}'),
        subtitle: const Text('Ожидает проверки'),
        trailing: const Icon(Icons.chevron_right),
        onTap: _busy ? null : () => _review(item['id'] as String),
      ),
    ])),
  );
}
