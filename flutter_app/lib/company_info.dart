import 'package:flutter/material.dart';
import 'app_language.dart';
import 'package:url_launcher/url_launcher.dart';

/// Informational preview. Legal texts require owner and legal review
/// before real bookings, payments or tracking are launched.
class CompanyInfoPage extends StatelessWidget {
  const CompanyInfoPage({super.key, this.initialTab = 0});

  final int initialTab;

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
    length: 4,
    initialIndex: initialTab,
    child: Scaffold(
      appBar: AppBar(
        title: Text(pdLabel(context, 'PRIVATE DRIVE · Информация')),
        bottom: const TabBar(isScrollable: true, tabs: [
          Tab(text: 'О компании'),
          Tab(text: 'Соглашение'),
          Tab(text: 'Конфиденциальность'),
          Tab(text: 'Отмена и возврат'),
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
            Text(pdLabel(context, 'Связаться с нами'),
              style: TextStyle(fontWeight: FontWeight.bold, color: gold)),
            ListTile(
              key: const Key('company-email'),
              leading: const Icon(Icons.email_outlined),
              title: const Text('eurobaltictransfer@gmail.com'),
              subtitle: Text(pdLabel(context, 'Электронная почта')),
              onTap: () => _launch(context, Uri(
                scheme: 'mailto', path: 'eurobaltictransfer@gmail.com')),
            ),
            ListTile(
              key: const Key('company-telegram-support'),
              leading: const Icon(Icons.forum_outlined),
              title: Text(pdLabel(context, 'Чат поддержки PRIVATE DRIVE')),
              subtitle: const Text('Telegram @PrivatDraiv · контакт из прежнего Mini App'),
              onTap: () => _launch(context,
                Uri.parse('https://t.me/PrivatDraiv')),
            ),
            ListTile(
              key: const Key('company-telegram-channel'),
              leading: const Icon(Icons.campaign_outlined),
              title: const Text('@PrivateDriveTransfer'),
              subtitle: Text(pdLabel(context, 'Официальный Telegram-канал')),
              onTap: () => _launch(context,
                Uri.parse('https://t.me/PrivateDriveTransfer')),
            ),

            ListTile(
              key: const Key('company-website'),
              leading: const Icon(Icons.language),
              title: Text(pdLabel(context, 'Сайт PRIVATE DRIVE')),
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
            Text(pdLabel(context, 'Пользовательское соглашение · проект'),
              style: TextStyle(color: gold, fontWeight: FontWeight.bold,
                fontSize: 19)),
            _paragraph('Редакция для предварительного тестирования: '
              '19.11.2026. Не является окончательной публичной офертой.'),
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
              'eurobaltictransfer@gmail.com. Ссылка на групповой чат '
              'PRIVATE DRIVE будет добавлена после подтверждения.'),
            _paragraph('5. До оплаты пассажир должен увидеть '
              'итоговую цену в евро, включённые услуги, возможные '
              'доплаты за ожидание и условия отмены. Платные опции '
              'нельзя включать без явного выбора.'),
            _paragraph('6. После подтверждения заказа пассажир '
              'получает сведения о маршруте, назначенном пилоте '
              'и способе связи. Подтверждение оплаты должно '
              'отличаться от подтверждения поездки.'),
            _paragraph('7. Претензии, возвраты и ошибки списания: '
              'eurobaltictransfer@gmail.com. Пользователь сохраняет '
              'права, предусмотренные обязательным законодательством '
              'о защите потребителей.'),
            _paragraph('8. Пользователь не должен передавать третьим лицам '
              'пароли и коды подтверждения. Пилот использует GPS '
              'только для выполнения работы и согласно уведомлению '
              'о конфиденциальности.'),
            _paragraph('9. Перед выпуском публичной версии необходимо '
              'подтвердить юридические реквизиты, статус PRIVATE DRIVE '
              'как перевозчика или посредника, страхование, порядок '
              'разрешения споров и применимое литовское право.'),
          ],
        ),
        ListView(key: const Key('company-privacy-tab'),
          padding: const EdgeInsets.all(18),
          children: [
            Text(pdLabel(context, 'Политика конфиденциальности · проект'),
              style: TextStyle(color: gold, fontWeight: FontWeight.bold,
                fontSize: 19)),
            _paragraph('Предварительная редакция: 19.11.2026. '
              'Для производственного запуска потребуется юридическое '
              'согласование и подтверждение фактических обработчиков данных.'),
            _paragraph('1. Контролёр данных: YAUHENI IVANTSOU '
              '(PRIVATE DRIVE). Контакт: eurobaltictransfer@gmail.com.'),
            _paragraph('2. При реальном бронировании могут обрабатываться '
              'имя, номер телефона, адреса посадки и назначения, '
              'данные заказа и оплаты, отзывы и обращения поддержки. '
              'GPS пилота должен обрабатываться лишь при '
              'разрешённой геолокации и выполнении работы.'),
            _paragraph('3. Цели и предполагаемые основания GDPR: '
              'создание аккаунта и выполнение бронирования — '
              'исполнение договора или подготовка к нему; '
              'бухгалтерские документы — юридическая обязанность; '
              'защита от мошенничества и обработка обращений — '
              'законный интерес при соблюдении баланса прав; '
              'необязательная реклама — отдельное согласие. '
              'Окончательная правовая оценка требуется до запуска.'),
            _paragraph('4. Данные GPS: при выданном разрешении '
              'координаты пилота могут использоваться для отображения '
              'подачи и хода поездки. Пассажиру следует показывать '
              'только данные, необходимые для конкретного заказа. '
              'Разрешение Android на геолокацию не заменяет '
              'уведомления GDPR и не даёт права на скрытое слежение.'),
            _paragraph('5. Возможные получатели: назначенный пилот, '
              'диспетчер, провайдеры хостинга, карт, SMS-проверки, '
              'платёжной обработки и поддержки. Их точные названия, '
              'местонахождение, трансграничные передачи и '
              'правовые гарантии необходимо указать после аудита.'),
            _paragraph('6. Сроки хранения: данные заказа и финансовые '
              'документы сохраняются только на документально '
              'обоснованные сроки по соответствующим основаниям. '
              'Точные сроки для аккаунта, GPS, чатов, истории '
              'и бухгалтерии должны быть утверждены до запуска.'),
            _paragraph('7. Права по GDPR: получение информации, '
              'доступ, исправление, удаление в применимых случаях, '
              'ограничение обработки, переносимость, возражение '
              'и отзыв ранее выданного согласия. Отзыв не влияет '
              'на законность обработки до отзыва. Запросы: '
              'eurobaltictransfer@gmail.com. Можно также '
              'обратиться в Государственную инспекцию по защите '
              'данных Литвы (VDAI).'),
            _paragraph('8. Защита: доступ к заказам должен быть '
              'ограничен ролями и идентификатором заказа; '
              'передача по сети — через HTTPS, без хранения '
              'секретных токенов в открытом виде. Эти меры '
              'подлежат проверке до реальных поездок.'),
            _paragraph('9. В локальном режиме DEMO тестовые заказы '
              'не создают рабочее бронирование. Картографические '
              'тайлы, поиск адресов и маршрутизация могут '
              'обращаться к внешним сервисам; для публичной '
              'версии их перечень и передаваемые данные '
              'необходимо раскрыть в политике.'),
            _paragraph('10. Перед запуском: проверить фактическую '
              'карту обработки данных и сроки хранения, составить '
              'перечень процессоров, проанализировать необходимость '
              'DPIA для GPS-мониторинга и проверить механизм '
              'обработки запросов на удаление данных.'),
          ],
        ),
        ListView(key: const Key('company-refunds-tab'),
          padding: const EdgeInsets.all(18),
          children: [
            Text('Отмена заказа и возврат · проект',
              style: TextStyle(color: gold, fontWeight: FontWeight.bold,
                fontSize: 19)),
            _paragraph('Редакция для обсуждения: 19.11.2026. '
              'Условия ниже не применяются к реальным платежам '
              'до их юридического утверждения и публикации '
              'до заключения договора.'),
            _paragraph('1. Предлагаемое правило: при отмене '
              'не позднее пяти минут после подтверждения '
              'бронирования — возврат 100% оплаченной суммы, '
              'если услуга ещё не была оказана.'),
            _paragraph('2. Предлагаемое правило после пяти минут: '
              'удержание до 20% только при законном основании '
              'и при условии предварительного ясного уведомления '
              'пассажира. Итоговые правила должны учитывать '
              'статус пилота, фактически понесённые расходы, '
              'обязательные права потребителя и момент подачи.'),
            _paragraph('3. При отмене со стороны PRIVATE DRIVE '
              'или невозможности оказать оплаченную услугу '
              'предусматривается полный возврат, '
              'если иное не требуется обязательным правом.'),
            _paragraph('4. Способ и срок возврата, рассмотрение '
              'споров по ожиданию, опозданию или неявке '
              'должны быть точно описаны до приёма оплаты. '
              'Возврат не должен зависеть от согласия '
              'на маркетинговые сообщения.'),
            _paragraph('5. Запрос на возврат: '
              'eurobaltictransfer@gmail.com с номером заказа. '
              'Не отправляйте полные номера банковских карт '
              'или SMS-коды в переписке.'),
            _paragraph('6. Для пассажирских перевозок правила '
              'общего 14-дневного отказа от дистанционной покупки '
              'не следует обещать автоматически: применимость '
              'исключений и специальных норм нужно юридически '
              'проверить для конкретной модели сервиса.'),
          ],
        ),
      ]),
    ),
  );
}
