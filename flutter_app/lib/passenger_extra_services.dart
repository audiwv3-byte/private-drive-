import 'package:flutter/material.dart';
import 'demo_trip_store.dart';
import 'passenger_orders_demo.dart';

/// Optional standalone service bookings in the isolated, payment-free demo.
/// No production API is contacted and no real vehicle assistance is dispatched.
enum ExtraServiceType { jumpstart, delivery }

class PassengerExtraServices extends StatefulWidget {
  const PassengerExtraServices({
    super.key,
    required this.type,
    required this.tripStore,
  });
  final ExtraServiceType type;
  final DemoTripStore tripStore;

  @override
  State<PassengerExtraServices> createState() =>
      _PassengerExtraServicesState();
}

class _PassengerExtraServicesState extends State<PassengerExtraServices> {
  final _from = TextEditingController();
  final _to = TextEditingController();
  final _notes = TextEditingController();
  DateTime? _date;
  TimeOfDay? _time;
  String _payment = 'Карта';

  bool get _jumpstart => widget.type == ExtraServiceType.jumpstart;
  String get _title => _jumpstart ? 'Запуск автомобиля' : 'Доставка товаров';

  bool get _isAdvanceBooking => _date != null || _time != null;
  bool get _cashBlockedForAdvance =>
      _isAdvanceBooking && _payment == 'Наличные';

  bool get _valid => !_cashBlockedForAdvance && !widget.tripStore.isActive &&
      _from.text.trim().isNotEmpty &&
      (_jumpstart || (_to.text.trim().isNotEmpty &&
          _to.text.trim().toLowerCase() != _from.text.trim().toLowerCase()));

  @override
  void initState() {
    super.initState();
    _from.addListener(_refresh);
    _to.addListener(_refresh);
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _from.dispose();
    _to.dispose();
    _notes.dispose();
    super.dispose();
  }

  void _create() {
    if (!_valid) return;
    final current = DateTime.now();
    final date = _date ?? DateUtils.dateOnly(current);
    final time = _time ?? TimeOfDay.fromDateTime(current);
    final when = DateTime(date.year, date.month, date.day,
        time.hour, time.minute);
    final created = widget.tripStore.create(
      from: _from.text.trim(),
      to: _jumpstart ? 'Помощь на месте' : _to.text.trim(),
      paymentMethod: _payment,
      advanceBooking: _isAdvanceBooking,
      departure: when,
      rideType: _title,
      estimatedFareEur: 20,
      services: [
        _title,
        if (_notes.text.trim().isNotEmpty)
          'Комментарий: ${_notes.text.trim()}',
      ],
    );
    if (created) {
      Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => PassengerOrdersDemo(tripStore: widget.tripStore)));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(_title)),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          Icon(_jumpstart ? Icons.battery_charging_full
            : Icons.shopping_bag_outlined, size: 54,
            color: const Color(0xFFDDC184)),
          const SizedBox(height: 12),
          Text(_title, style: const TextStyle(
            fontSize: 23, fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          Text(_jumpstart
            ? 'Разрядился аккумулятор? Пилот поможет запустить '
              'автомобиль с помощью пусковых проводов.'
            : 'Заберём покупки из магазина и доставим '
              'по указанному адресу.'),
          const SizedBox(height: 14),
          const Text('Предварительная стоимость: 20 €',
            key: Key('extra-service-price'),
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold,
              color: Color(0xFFDDC184))),
          const Text('Наличие пилота, территория обслуживания '
            'и окончательная стоимость подтверждаются диспетчером '
            'до оплаты. Демо не выполняет реальных заказов.',
            style: TextStyle(fontSize: 12)),
          const SizedBox(height: 20),
          TextField(
            key: const Key('extra-service-from'),
            readOnly: widget.tripStore.isActive,
            controller: _from,
            maxLength: 200,
            decoration: InputDecoration(
              labelText: _jumpstart ? 'Адрес автомобиля'
                : 'Адрес магазина / место получения',
              border: const OutlineInputBorder(),
              counterText: '',
            ),
          ),
          if (!_jumpstart) ...[
            const SizedBox(height: 12),
            TextField(
              key: const Key('extra-service-to'),
              readOnly: widget.tripStore.isActive,
              controller: _to,
              maxLength: 200,
              decoration: const InputDecoration(
                labelText: 'Адрес доставки',
                border: OutlineInputBorder(),
                counterText: '',
              ),
            ),
          ],
          const SizedBox(height: 10),
          TextField(
            key: const Key('extra-service-notes'),
            readOnly: widget.tripStore.isActive,
            controller: _notes,
            maxLength: 500,
            maxLines: 3,
            decoration: InputDecoration(
              labelText: _jumpstart
                ? 'Марка автомобиля и комментарий'
                : 'Название магазина, товары и комментарий',
              border: const OutlineInputBorder(),
            ),
          ),
          Row(children: [
            Expanded(child: OutlinedButton.icon(
              key: const Key('extra-service-date'),
              icon: const Icon(Icons.calendar_today_outlined),
              label: Text(_date == null
                  ? 'Дата'
                  : '${_date!.day}.${_date!.month}.${_date!.year}'),
              onPressed: widget.tripStore.isActive ? null : () async {
                final d = await showDatePicker(
                  context: context,
                  initialDate: _date ?? DateTime.now(),
                  firstDate: DateUtils.dateOnly(DateTime.now()),
                  lastDate: DateTime.now().add(const Duration(days: 365)));
                if (d != null && mounted && !widget.tripStore.isActive) setState(() {
                  _date = d;
                  if (_cashBlockedForAdvance) _payment = 'Карта';
                });
              },
            )),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton.icon(
              key: const Key('extra-service-time'),
              icon: const Icon(Icons.schedule),
              label: Text(_time?.format(context) ?? 'Время'),
              onPressed: widget.tripStore.isActive ? null : () async {
                final t = await showTimePicker(
                  context: context,
                  initialTime: _time ?? TimeOfDay.now());
                if (t != null && mounted && !widget.tripStore.isActive) setState(() {
                  _time = t;
                  if (_cashBlockedForAdvance) _payment = 'Карта';
                });
              },
            )),
          ]),
          const SizedBox(height: 14),
          const Text('Способ оплаты · выбор без списания'),
          Wrap(spacing: 8, children: [
            for (final method in [
              'Карта', 'PayPal', 'Банковский перевод', 'Криптовалюта',
              'Наличные',
            ])
              ChoiceChip(
                key: Key('extra-payment-$method'),
                label: Text(method),
                selected: _payment == method,
                onSelected: widget.tripStore.isActive ||
                    (_isAdvanceBooking && method == 'Наличные') ? null
                    : (_) => setState(() => _payment = method),
              ),
          ]),
          if (_isAdvanceBooking)
            const Text('Предварительные заявки принимаются только по безналичной оплате.',
              key: Key('extra-advance-cash-notice')),
          if (widget.tripStore.isActive)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Text('Сначала заверши активную заявку.',
                style: TextStyle(color: Colors.orangeAccent)),
            ),
          const SizedBox(height: 15),
          FilledButton.icon(
            key: const Key('extra-service-submit'),
            onPressed: _valid ? _create : null,
            icon: const Icon(Icons.task_alt),
            label: const Text('Создать тестовую заявку · 20 €'),
          ),
        ],
      ),
    ),
  );
}
