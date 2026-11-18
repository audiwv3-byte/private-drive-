import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Informational preview. Legal texts require owner and legal review
/// before real bookings, payments or tracking are launched.
class CompanyInfoPage extends StatelessWidget {
  const CompanyInfoPage({super.key});

  static const gold = Color(0xFFDDC184);

  Future<void> _launch(BuildContext context, Uri target) async {
    try {
      if (await launchUrl(target, mode: LaunchMode.externalApplication)) {
        return;
      }
    } catch (_) {
      // If a handler isn't installed, show a visible error instead.
    }
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Не удалось открыть ссылку: $target'),
      ));
    }
  }

  Widget _paragraph(String value) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Text(value),
  );

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 3,
    child: Scaffold(
      appBar: AppBar(
        title: const Text('PRIVATE DRIVE · Информация'),
        bottom: const TabBar(isScrollable: true, tabs: [
          Tab(text: 'О компании'),
          Tab(text: 'Соглашение'),
          Tab(text: 'Конфиденциальность'),
        ]),
      ),
      body: TabBarView(children: [
        ListView(key: const Key('company-contacts-tab'),
          padding: const EdgeInsets.all(18),
          children: [
            const Text('PRIVATE DRIVE', style: TextStyle(
              fontSize: 24, fontWeight: FontWeight.bold, color: gold)),
            _paragraph('Сервис предварительного заказа поездок '
              'и персональных трансферов в Литве. '
              'В прежних материалах — Euro Baltic Transfer.'),
            _paragraph('Статус: тестовая версия мобильного приложения. '
              'Реальные заказы и платежи в демоверсии не проводятся.'),
            _paragraph('Оператор проекта: YAUHENI IVANTSOU. '
              'Индивидуальная деятельность в Литве '
              '(Individualios veiklos pažymos Nr. 1374775). '
              'Сведения предоставлены владельцем проекта.'),
            const Text('Связаться с нами',
              style: TextStyle(fontWeight: FontWeight.bold, color: gold)),
            ListTile(
              key: const Key('company-email'),
              leading: const Icon(Icons.email_outlined),
              title: const Text('eurobaltictransfer@gmail.com'),
              subtitle: const Text('Электронная почта'),
              onTap: () => _launch(context, Uri(
                scheme: 'mailto', path: 'eurobaltictransfer@gmail.com')),
            ),
            ListTile(
              key: const Key('company-telegram-support'),
              leading: const Icon(Icons.chat_outlined),
              title: const Text('@EuroBalticTransferBot'),
              subtitle: const Text('Связь через Telegram-бота'),
              onTap: () => _launch(context,
                Uri.parse('https://t.me/EuroBalticTransferBot')),
            ),
            ListTile(
              key: const Key('company-telegram-channel'),
              leading: const Icon(Icons.campaign_outlined),
              title: const Text('@PrivateDriveTransfer'),
              subtitle: const Text('Официальный Telegram-канал'),
              onTap: () => _launch(context,
                Uri.parse('https://t.me/PrivateDriveTransfer')),
            ),
            _paragraph('Ссылка на отдельный групповой чат PRIVATE DRIVE '
              'ещё не подтверждена. Непроверенная ссылка не публикуется.'),
            ListTile(
              key: const Key('company-website'),
              leading: const Icon(Icons.language),
              title: const Text('Сайт PRIVATE DRIVE'),
              subtitle: const Text('wilsonpark.pythonanywhere.com'),
              onTap: () => _launch(context,
                Uri.parse('https://wilsonpark.pythonanywhere.com/')),
            ),
            _paragraph('Для официального запуска потребуется уточнить '
              'актуальные контактные и регистрационные сведения, '
              'публичные правила обслуживания и политику обработки данных.'),
          ],
        ),
        ListView(key: const Key('company-terms-tab'),
          padding: const EdgeInsets.all(18),
          children: [
            const Text('Пользовательское соглашение · проект',
              style: TextStyle(color: gold, fontWeight: FontWeight.bold,
                fontSize: 19)),
            _paragraph('Редакция для предварительного тестирования: '
              '18.11.2026. Не является окончательной публичной офертой.'),
            _paragraph('1. PRIVATE DRIVE предоставляет интерфейс '
              'для предварительного запроса поездок и трансферов. '
              'В данной демоверсии заявки, подтверждения пилотов '
              'и оценки существуют только в рамках тестовой сессии.'),
            _paragraph('2. В рабочей версии цена, маршрут, дополнительные '
              'услуги, способы оплаты и условия отмены должны быть '
              'показаны пользователю до подтверждения заказа.'),
            _paragraph('3. Фактическая поездка возможна лишь после '
              'подтверждения заявки уполномоченным диспетчером '
              'и принятия назначенным пилотом.'),
            _paragraph('4. Контактная поддержка: '
              'eurobaltictransfer@gmail.com или @EuroBalticTransferBot.'),
            _paragraph('5. Условия возврата, ответственность сторон, '
              'порядок претензий и обязательная потребительская '
              'информация должны быть дополнены и юридически '
              'проверены перед включением реального бронирования.'),
          ],
        ),
        ListView(key: const Key('company-privacy-tab'),
          padding: const EdgeInsets.all(18),
          children: [
            const Text('Политика конфиденциальности · проект',
              style: TextStyle(color: gold, fontWeight: FontWeight.bold,
                fontSize: 19)),
            _paragraph('Предварительная редакция: 18.11.2026. '
              'Для производственного запуска потребуется юридическое '
              'согласование и подтверждение фактических обработчиков данных.'),
            _paragraph('1. Контролёр данных: YAUHENI IVANTSOU '
              '(PRIVATE DRIVE). Контакт: eurobaltictransfer@gmail.com.'),
            _paragraph('2. При реальном бронировании могут обрабатываться '
              'имя, номер телефона, адреса посадки и назначения, '
              'данные заказа и оплаты, отзывы и обращения поддержки. '
              'GPS пилота должен обрабатываться лишь при '
              'разрешённой геолокации и выполнении работы.'),
            _paragraph('3. Цели обработки: организация поездок, '
              'связь с клиентом, исполнение правовых обязанностей '
              'и безопасность сервиса. Правовые основания '
              'и сроки хранения должны быть документированы '
              'до запуска сервера.'),
            _paragraph('4. Клиенты и пилоты вправе обращаться '
              'по вопросам доступа, исправления, удаления '
              'и других применимых прав в сфере защиты данных. '
              'Контакт: eurobaltictransfer@gmail.com.'),
            _paragraph('5. В данной локальной демоверсии тестовые '
              'заказы и рейтинги не отправляются в рабочую систему. '
              'Карта может обращаться к внешним поставщикам '
              'картографических тайлов и маршрутов.'),
          ],
        ),
      ]),
    ),
  );
}
