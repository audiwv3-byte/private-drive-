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
  bool _busy = false;
  String _message = '';
  @override
  void initState() { super.initState(); _load(); }
  Future<void> _load() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final result = await widget.api.request('GET', 'queue');
      if (mounted) setState(() {
        _items = result['items'] as List<dynamic>;
        _message = _items.isEmpty ? 'Нет фотографий на проверке' : '';
      });
    } catch (_) {
      if (mounted) setState(() => _message = 'Не удалось получить очередь. Проверь права и подключение.');
    } finally { if (mounted) setState(() => _busy = false); }
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
      for (final item in _items) ListTile(
        title: Text('Пилот: ${item['user_id']}'),
        subtitle: const Text('Ожидает проверки'),
        trailing: const Icon(Icons.chevron_right),
        onTap: _busy ? null : () => _review(item['id'] as String),
      ),
    ])),
  );
}
