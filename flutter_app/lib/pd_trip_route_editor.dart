import 'package:flutter/material.dart';

class PdTripRouteEditor extends StatefulWidget {
  const PdTripRouteEditor({
    super.key,
    required this.origin,
    required this.destination,
    required this.stops,
    this.pickupLocked = false,
  });

  final String origin;
  final String destination;
  final List<String> stops;
  final bool pickupLocked;

  @override
  State<PdTripRouteEditor> createState() => _PdTripRouteEditorState();
}

class _PdTripRouteEditorState extends State<PdTripRouteEditor> {
  final _form = GlobalKey<FormState>();
  late final _origin = TextEditingController(text: widget.origin);
  late final _destination = TextEditingController(text: widget.destination);
  late final _stops = widget.stops
      .map((address) => TextEditingController(text: address))
      .toList();
  final _removed = <TextEditingController>[];

  @override
  void dispose() {
    _origin.dispose();
    _destination.dispose();
    for (final field in [..._stops, ..._removed]) {
      field.dispose();
    }
    super.dispose();
  }

  Widget _field(
    TextEditingController controller,
    String label, {
    bool readOnly = false,
    VoidCallback? onRemove,
  }) {
    return TextFormField(
      key: ObjectKey(controller),
      controller: controller,
      readOnly: readOnly,
      maxLength: 200,
      validator: (value) =>
          value == null || value.trim().isEmpty ? 'Укажи адрес' : null,
      decoration: InputDecoration(
        labelText: label,
        counterText: '',
        suffixIcon: onRemove == null
            ? null
            : IconButton(
                tooltip: 'Удалить остановку',
                onPressed: onRemove,
                icon: const Icon(Icons.close),
              ),
      ),
    );
  }

  void _save() {
    if (!_form.currentState!.validate()) return;
    Navigator.pop(context, <String, dynamic>{
      'from': _origin.text.trim(),
      'to': _destination.text.trim(),
      'stops': _stops.map((field) => field.text.trim()).toList(),
    });
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Маршрут поездки'),
    scrollable: true,
    content: Form(
      key: _form,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _field(_origin, 'Точка подачи', readOnly: widget.pickupLocked),
          for (final (index, field) in _stops.indexed)
            _field(
              field,
              'Остановка ${index + 1}',
              onRemove: () {
                setState(() {
                  _stops.remove(field);
                  _removed.add(field);
                });
              },
            ),
          if (_stops.length < 3)
            TextButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Добавить остановку'),
              onPressed: () =>
                  setState(() => _stops.add(TextEditingController())),
            ),
          _field(_destination, 'Куда'),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Отмена'),
      ),
      FilledButton(onPressed: _save, child: const Text('Сохранить')),
    ],
  );
}
