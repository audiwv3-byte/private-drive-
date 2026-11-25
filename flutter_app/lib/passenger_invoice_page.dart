import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_language.dart';
import 'demo_trip_store.dart';
import 'taxi_fare.dart';

class PassengerInvoicePage extends StatelessWidget {
  const PassengerInvoicePage({super.key, required this.tripStore});

  final DemoTripStore? tripStore;

  @override
  Widget build(BuildContext context) {
    String tr(String ru, String lt, String en) => pdTr(context, ru, lt, en);
    final store = tripStore;
    final trip = store?.status == DemoTripStatus.finished ? store?.trip : null;
    final title = tr('Фактуры за поездки', 'Kelionių sąskaitos', 'Trip invoices');
    final draftTitle = tr('Черновик · PRIVATE DRIVE', 'Juodraštis · PRIVATE DRIVE',
      'Draft · PRIVATE DRIVE');
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: SafeArea(child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (trip == null)
            Text(tr('Черновик доступен после завершения поездки.',
              'Juodraštis prieinamas pasibaigus kelionei.',
              'A draft is available after the trip is completed.'))
          else
            Card(child: ListTile(
              leading: const Icon(Icons.receipt_long_outlined),
              title: Text(trip.routeLabel),
              trailing: const Icon(Icons.chevron_right),
              onTap: () {
                final locale = MaterialLocalizations.of(context);
                final when = trip.departure.toLocal();
                final fare = trip.estimatedFareCents ??
                    (trip.estimatedFareEur == null ? null : trip.estimatedFareEur! * 100);
                final distance = trip.plannedDistanceMetres;
                final seconds = trip.plannedDurationSeconds;
                final unavailable = tr('Нет данных', 'Nėra duomenų', 'Unavailable');
                final rows = <(String, String)>[
                  (tr('Маршрут', 'Maršrutas', 'Route'), trip.routeLabel),
                  (tr('Дата и время подачи', 'Paėmimo data ir laikas', 'Pickup date and time'),
                    '${locale.formatFullDate(when)} · ${locale.formatTimeOfDay(TimeOfDay.fromDateTime(when), alwaysUse24HourFormat: true)}'),
                  (tr('Расчётное расстояние', 'Planuojamas atstumas', 'Estimated distance'),
                    distance == null ? unavailable : '${(distance / 1000).toStringAsFixed(1)} km'),
                  (tr('Расчётное время', 'Planuojama trukmė', 'Estimated duration'),
                    seconds == null ? unavailable : '${(seconds / 60).ceil()} min'),
                  (tr('Предварительная сумма', 'Preliminari suma', 'Estimated amount'),
                    fare == null ? unavailable : PdTaxiFare.euros(fare)),
                  (tr('Способ оплаты', 'Mokėjimo būdas', 'Payment method'),
                    pdLabel(context, trip.paymentMethod)),
                  if (trip.services.isNotEmpty)
                    (tr('Услуги', 'Paslaugos', 'Services'), trip.services.join(', ')),
                ];
                showModalBottomSheet<void>(
                  context: context,
                  isScrollControlled: true,
                  showDragHandle: true,
                  builder: (sheetContext) => SafeArea(child: FractionallySizedBox(
                    heightFactor: 0.8,
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                      children: [
                        Text(draftTitle, style: Theme.of(context).textTheme.titleLarge),
                        for (final (label, value) in rows)
                          ListTile(contentPadding: EdgeInsets.zero,
                            title: Text(label), subtitle: SelectableText(value)),
                        FilledButton.icon(
                          icon: const Icon(Icons.copy),
                          label: Text(tr('Скопировать черновик', 'Kopijuoti juodraštį', 'Copy draft')),
                          onPressed: () async {
                            await Clipboard.setData(ClipboardData(text: [
                              draftTitle,
                              for (final (label, value) in rows) '$label: $value',
                            ].join('\n')));
                            if (sheetContext.mounted) Navigator.pop(sheetContext);
                          },
                        ),
                      ],
                    ),
                  )),
                );
              },
            )),
        ],
      )),
    );
  }
}
