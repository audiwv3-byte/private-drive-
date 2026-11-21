import 'package:flutter/material.dart';

/// Read-only screens for the pilot cockpit statistics.
///
/// No statistics API is connected here. Never infer earnings, acceptance,
/// reviews, levels or rewards from the local demonstration trip.
enum PilotStatisticSection {
  income,
  acceptance,
  rating,
  level,
  rewards,
}

class PilotStatisticsPage extends StatelessWidget {
  const PilotStatisticsPage({super.key, required this.section});

  final PilotStatisticSection section;

  static const _gold = Color(0xFFDDC184);
  static const _surface = Color(0xFF10151D);

  String get _title => switch (section) {
    PilotStatisticSection.income => 'Доход',
    PilotStatisticSection.acceptance => 'Принятие заказов',
    PilotStatisticSection.rating => 'Рейтинг пилота',
    PilotStatisticSection.level => 'Уровень пилота',
    PilotStatisticSection.rewards => 'Поощрения',
  };

  IconData get _icon => switch (section) {
    PilotStatisticSection.income => Icons.euro,
    PilotStatisticSection.acceptance => Icons.call_received,
    PilotStatisticSection.rating => Icons.star_outline,
    PilotStatisticSection.level => Icons.workspace_premium_outlined,
    PilotStatisticSection.rewards => Icons.card_giftcard_outlined,
  };

  String get _description => switch (section) {
    PilotStatisticSection.income =>
      'История поездок и подтверждённый доход появятся после '
      'подключения защищённого источника статистики.',
    PilotStatisticSection.acceptance =>
      'Статистика за сегодня, 7 дней, 30 дней и всё время '
      'появится после подключения событий предложений заказов. '
      'Для уровня пилота используется период 30 дней.',
    PilotStatisticSection.rating =>
      'Общий рейтинг и рейтинг за последние 30 дней появятся '
      'после подключения подтверждённых оценок пассажиров. '
      'Для расчёта уровня требуется не менее 10 оценок за 30 дней.',
    PilotStatisticSection.level =>
      'Уровни Silver, Gold и Platinum будут определяться по '
      'утверждённым правилам после подключения серверной статистики. '
      'Никакой уровень сейчас не назначается.',
    PilotStatisticSection.rewards =>
      'Задания, достижения и статусы бонусов появятся после '
      'подключения защищённого кабинета поощрений. '
      'Реальные начисления и выплаты отключены.',
  };

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: Key('pilot-statistics-page-${section.name}'),
      backgroundColor: const Color(0xFF090D14),
      appBar: AppBar(
        title: Text(_title),
        backgroundColor: _surface,
        leading: IconButton(
          key: const Key('pilot-statistics-back'),
          tooltip: 'Вернуться на карту',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Icon(_icon, size: 54, color: _gold),
                const SizedBox(height: 18),
                Text(
                  _title,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 23, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 24),
                Container(
                  padding: const EdgeInsets.all(22),
                  decoration: BoxDecoration(
                    color: _surface,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: const Color(0x667D683F)),
                  ),
                  child: const Column(
                    children: [
                      Icon(Icons.query_stats_outlined, color: _gold, size: 34),
                      SizedBox(height: 10),
                      Text(
                        'Нет данных',
                        key: Key('pilot-statistics-no-data'),
                        style: TextStyle(fontSize: 21,
                          fontWeight: FontWeight.w700, color: _gold),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                Text(_description,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white70, height: 1.4)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
