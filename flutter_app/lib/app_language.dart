import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One language selection shared across all native Android demo routes.
/// A missing translation stays visible in Russian rather than disappearing.
class PdLanguage extends ChangeNotifier {
  String _value = 'RU';
  bool _hasSelection = false;
  bool _hasAcknowledgedTerms = false;
  String get value => _value;
  bool get hasSelection => _hasSelection;
  bool get hasAcknowledgedTerms => _hasAcknowledgedTerms;
  static const _storageKey = 'pd_native_language_v1';
  static const _termsKey = 'pd_native_terms_acknowledged_v1';

  Future<void> restore() async {
    try {
      final preferences = SharedPreferencesAsync();
      final stored = await preferences.getString(_storageKey);
      final acknowledged = await preferences.getBool(_termsKey) ?? false;
      if (stored == 'RU' || stored == 'LT' || stored == 'EN') {
        _value = stored!;
        _hasSelection = true;
      }
      _hasAcknowledgedTerms = acknowledged;
      notifyListeners();
    } catch (_) {
      // Offline preview also runs in widget tests without platform storage.
    }
  }

  Future<void> acknowledgeTerms() async {
    if (_hasAcknowledgedTerms) return;
    try {
      await SharedPreferencesAsync().setBool(_termsKey, true);
    } catch (_) {
      // Keep the acknowledgement for the current run if storage is unavailable.
    }
    _hasAcknowledgedTerms = true;
    notifyListeners();
  }

  void set(String language, {bool persist = true}) {
    if (language != 'RU' && language != 'LT' && language != 'EN') return;
    final changed = _value != language || (persist && !_hasSelection);
    if (!changed) return;
    _value = language;
    if (persist) _hasSelection = true;
    notifyListeners();
    if (persist) {
      try {
        SharedPreferencesAsync().setString(_storageKey, language)
            .catchError((Object _) {});
      } catch (_) {}
    }
  }
}

final PdLanguage pdLanguage = PdLanguage();

class PdLanguageScope extends InheritedNotifier<PdLanguage> {
  const PdLanguageScope({
    super.key,
    required PdLanguage language,
    required super.child,
  }) : super(notifier: language);

  static PdLanguage of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<PdLanguageScope>()?.notifier ??
      pdLanguage;
}

/// Compact selector: selecting a language notifies every mounted demo route.
/// It can be used by passengers without returning to the sign-in screen.
class PdLanguageMenu extends StatelessWidget {
  const PdLanguageMenu({super.key});

  @override
  Widget build(BuildContext context) {
    final language = PdLanguageScope.of(context);
    final selected = language.value;
    return PopupMenuButton<String>(
      key: const Key('passenger-global-language-menu'),
      tooltip: pdTr(context, 'Язык приложения', 'Programėlės kalba', 'App language'),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6),
        child: Text(
          switch (selected) {
            'LT' => '🇱🇹 LT',
            'EN' => '🇬🇧 EN',
            _ => '🇷🇺 RU',
          },
          key: const Key('passenger-language-flag'),
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
        ),
      ),
      initialValue: selected,
      onSelected: language.set,
      itemBuilder: (context) => const [
        PopupMenuItem<String>(
          key: Key('passenger-select-language-RU'),
          value: 'RU', child: Text('🇷🇺 RU')),
        PopupMenuItem<String>(
          key: Key('passenger-select-language-LT'),
          value: 'LT', child: Text('🇱🇹 LT')),
        PopupMenuItem<String>(
          key: Key('passenger-select-language-EN'),
          value: 'EN', child: Text('🇬🇧 EN')),
      ],
    );
  }
}

/// Only passenger-owned routes opt into translated UI.
/// Pilot, dispatcher, authentication and shared demo tools remain Russian.
class PdPassengerLanguageScope extends InheritedWidget {
  const PdPassengerLanguageScope({super.key, required super.child});

  static bool enabled(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<PdPassengerLanguageScope>() != null;

  @override
  bool updateShouldNotify(PdPassengerLanguageScope oldWidget) => false;
}

String pdTr(BuildContext context, String ru, String lt, String en) {
  if (!PdPassengerLanguageScope.enabled(context)) return ru;
  return pdEntryTr(context, ru, lt, en);
}

String pdEntryTr(BuildContext context, String ru, String lt, String en) =>
    switch (PdLanguageScope.of(context).value) {
      'LT' => lt,
      'EN' => en,
      _ => ru,
    };

/// Common UI labels used across pilot, passenger and dispatcher routes.
/// The business identifiers and fare-routing strings remain in Russian.
String pdLabel(BuildContext context, String ru) {
  if (!PdPassengerLanguageScope.enabled(context)) return ru;
  final language = PdLanguageScope.of(context).value;
  if (language == 'RU') return ru;
  final translations = _labels[ru];
  if (translations == null) return ru;
  return language == 'LT' ? translations[0] : translations[1];
}

const Map<String, List<String>> _labels = {
  'Сегодня · 0,00 €': ['Šiandien · 0,00 €', 'Today · €0.00'],
  'За неделю · 0,00 € · демо': ['Per savaitę · 0,00 € · demo', 'This week · €0.00 · demo'],
  'Баланс · нет подключённых выплат': ['Balansas · išmokos neprijungtos', 'Balance · payouts not connected'],
  'Стоимость заказа · по запросу': ['Užsakymo kaina · pagal užklausą', 'Booking fare · on request'],
  'Доход пилота · комиссия не настроена': ['Vairuotojo pajamos · komisiniai nenustatyti', 'Pilot earnings · commission not set'],
  'Входящий заказ · демо': ['Gautas užsakymas · demo', 'Incoming booking · demo'],
  'Стоимость · по запросу': ['Kaina · pagal užklausą', 'Fare · on request'],
  'Доход пилота · требуется тариф комиссии': ['Vairuotojo pajamos · reikia komisinių tarifo', 'Pilot earnings · commission rate required'],
  'Оплата ·': ['Mokėjimas ·', 'Payment ·'],
  'Стоимость заказа': ['Užsakymo kaina', 'Booking fare'],
  'Стоимость': ['Kaina', 'Fare'],
  'Пассажир · демо': ['Keleivis · demo', 'Passenger · demo'],
  'Локальный чат DEMO: сообщения доступны пассажиру в этом приложении, но не передаются между телефонами.': ['Vietinis DEMO pokalbis: keleivis mato žinutes šiame įrenginyje, bet jos nesiunčiamos tarp telefonų.', 'Local DEMO chat: the passenger can see messages in this app, but they are not sent between phones.'],
  'Я на месте': ['Aš jau vietoje', 'I have arrived'],
  'Я уже в пути': ['Jau važiuoju', 'On my way'],
  'Введите сообщение': ['Įveskite žinutę', 'Enter message'],
  'Отправить в демочат': ['Siųsti į demo pokalbį', 'Send to demo chat'],
  'Оцени завершённую поездку': ['Įvertinkite baigtą kelionę', 'Rate your completed trip'],
  'Поездка': ['Kelionė', 'Trip'],
  'Качество сервиса': ['Paslaugos kokybė', 'Service quality'],
  'Отправить оценку · демо': ['Pateikti įvertinimą · demo', 'Submit rating · demo'],
  'Тестовая оценка остаётся только на устройстве.': ['Bandomasis įvertinimas lieka tik šiame įrenginyje.', 'Demo rating stays on this device.'],
  'Открыть': ['Atidaryti', 'Open'],
  'Отмена через приложение недоступна на этом этапе поездки. Обратись к диспетчеру.': ['Šiame kelionės etape atšaukimas programėlėje negalimas. Susisiekite su dispečeriu.', 'Cancellation is unavailable at this stage. Contact dispatch.'],
  'Реестр других пилотов и документы появятся только после подключения защищённого API и проверки прав диспетчера.': ['Kitų vairuotojų sąrašas ir dokumentai pasirodys tik prijungus saugų API ir patikrinus dispečerio teises.', 'Other pilots and documents will appear only after secure API access and dispatcher permissions are verified.'],
  'Телефоны, профили и реальные пассажиры не загружаются без серверной авторизации диспетчера.': ['Telefonai, profiliai ir tikri keleiviai neįkeliami be dispečerio autorizavimo serveryje.', 'Phone numbers, profiles and real passengers are not loaded without dispatcher server authorization.'],
  '1 пилот с GPS · только локальная сессija': ['1 vairuotojas su GPS · tik vietinė sesija', '1 pilot with GPS · local session only'],
  'Подтверждённых GPS-точек нет. Для нескольких пилотов нужна защищённая серверная синхронизация.': ['Nėra patvirtintų GPS koordinačių. Keliems vairuotojams reikalingas saugus sinchronizavimas su serveriu.', 'No verified GPS positions. Multiple pilots require secure server synchronization.'],
  'Не удалось открыть ссылку': ['Nepavyko atidaryti nuorodos', 'Could not open link'],
  'Аккаунт': ['Paskyra', 'Account'],
  'Код запрошен. Введи полученный код подтверждения.': ['Kodas išsiųstas. Įveskite gautą patvirtinimo kodą.', 'Code requested. Enter the verification code.'],
  'Не удалось запросить код. Проверь подключение и данные.': ['Nepavyko gauti kodo. Patikrinkite ryšį ir duomenis.', 'Could not request a code. Check connection and details.'],
  'Код не подтверждён. Проверь код или срок действия.': ['Kodas nepatvirtintas. Patikrinkite kodą ir galiojimo laiką.', 'Code not verified. Check the code or expiry.'],
  'Тестовая сборка: сервер авторизации не подключён. Отправка SMS выключена.': ['Bandomoji versija: prisijungimo serveris neprijungtas. SMS siuntimas išjungtas.', 'Demo build: sign-in server not connected. SMS sending is disabled.'],
  'Вильнюс → Аэропорт Вильнюса': ['Vilnius → Vilniaus oro uostas', 'Vilnius → Vilnius Airport'],
  'Доход пилота': ['Vairuotojo pajamos', 'Pilot earnings'],
  'Сообщение пилота': ['Vairuotojo žinutė', 'Pilot message'],
  'Неизвестная ошибка': ['Nežinoma klaida', 'Unknown error'],
  'Только изолированный сервер. Без SMS и уведомлений ОС.': ['Tik izoliuotas serveris. Be SMS ir sistemos pranešimų.', 'Isolated server only. No SMS or system notifications.'],
  'Введите HTTPS-адрес': ['Įveskite HTTPS adresą', 'Enter HTTPS URL'],
  'HTTPS-адрес': ['HTTPS adresas', 'HTTPS address'],
  'Временный токен': ['Laikinas žetonas', 'Temporary token'],
  'Подключиться': ['Prisijungti', 'Connect'],
  'Создать тестовую заявку': ['Sukurti bandomąjį užsakymą', 'Create demo booking'],
  'Обновить статус': ['Atnaujinti būseną', 'Refresh status'],
  'Продолжить': ['Tęsti', 'Resume'],
  'Сообщение по заказу': ['Užsakymo žinutė', 'Booking message'],
  'Сообщения поездки · тестовый сервер': ['Kelionės žinutės · bandomasis serveris', 'Trip messages · test server'],
  'PRIVATE DRIVE · Тестовый сервер': ['PRIVATE DRIVE · Bandomasis serveris', 'PRIVATE DRIVE · Test server'],
  'Тестовый сервер · реальные заказы и оплата выключены': ['Bandomasis serveris · tikri užsakymai ir mokėjimai išjungti', 'Test server · real bookings and payments are disabled'],
  'Подключение только к изолированному тестовому серверу.': ['Jungiamasi tik prie izoliuoto bandomojo serverio.', 'Connection to isolated test server only.'],
  'Пилот': ['Vairuotojas', 'Pilot'],
  'Тестовый сервер': ['Bandomasis serveris', 'Test server'],
  'Сервис': ['Paslauga', 'Service'],
  'из 5': ['iš 5', 'out of 5'],
  'Банковский перевод': ['Bankinis pavedimas', 'Bank transfer'],
  'Криптовалюта': ['Kriptovaliuta', 'Cryptocurrency'],
  'Без радио': ['Be radijo', 'No radio'],
  'свой маршрут': ['individualus maršrutas', 'custom route'],
  'Цена по запросу': ['Kaina pagal užklausą', 'Price on request'],
  'Нет тестового заказа': ['Nėra bandomojo užsakymo', 'No demo booking'],
  'Заявка создана · ожидает назначения':
      ['Užsakymas sukurtas · laukiama priskyrimo', 'Booking created · awaiting assignment'],
  'Заказ принят · пилот готов к выезду':
      ['Užsakymas priimtas · vairuotojas pasiruošęs', 'Booking accepted · pilot ready'],
  'Пилот назначен · ожидает принятия':
      ['Vairuotojas paskirtas · laukiama priėmimo', 'Pilot assigned · awaiting acceptance'],
  'Остановка · демо': ['Sustojimas · demo', 'Stop · demo'],
  'Пилот едет к пассажиру': ['Vairuotojas važiuoja pas keleivį', 'Pilot driving to passenger'],
  'Поездка выполняется': ['Kelionė vyksta', 'Trip in progress'],
  'Заказ отменён пассажиром · демо':
      ['Keleivis atšaukė užsakymą · demo', 'Passenger cancelled booking · demo'],
  'Карта пилота не загрузилась':
      ['Nepavyko įkelti vairuotojo žemėlapio', 'Pilot map did not load'],
  'Повторить загрузку карты':
      ['Iš naujo įkelti žemėlapį', 'Reload map'],
  'Включить GPS': ['Įjungti GPS', 'Enable GPS'],
  'Выключить GPS': ['Išjungti GPS', 'Disable GPS'],
  'Центрировать карту': ['Centruoti žemėlapį', 'Center map'],
  'Назад': ['Atgal', 'Back'],
  'Новый назначенный заказ · демо':
      ['Naujas priskirtas užsakymas · demo', 'New assigned booking · demo'],
  'Принять': ['Priimti', 'Accept'],
  'Отклонить': ['Atmesti', 'Decline'],
  'Сымитировать новый заказ': ['Sukurti bandomąjį užsakymą', 'Simulate new booking'],
  'Принять следующий': ['Priimti kitą', 'Accept next'],
  'Пропустить': ['Praleisti', 'Skip'],
  'Связь с пассажиром · демо':
      ['Ryšys su keleiviu · demo', 'Passenger contact · demo'],
  'Написать': ['Rašyti', 'Message'],
  'Позвонить': ['Skambinti', 'Call'],
  'Позвонить пассажиру': ['Skambinti keleiviui', 'Call passenger'],
  'Понятно': ['Supratau', 'OK'],
  'Установи Waze: открыть его отдельно не удалось.':
      ['Įdiek Waze: nepavyko atidaryti programėlės.',
       'Install Waze: could not open the app.'],
  'PRIVATE DRIVE · Информация': ['PRIVATE DRIVE · Informacija', 'PRIVATE DRIVE · Information'],
  'Связаться с нами': ['Susisiekite su mumis', 'Contact us'],
  'Электронная почта': ['El. paštas', 'Email'],
  'Чат поддержки PRIVATE DRIVE':
      ['PRIVATE DRIVE pagalbos pokalbis', 'PRIVATE DRIVE support chat'],
  'Официальный Telegram-канал':
      ['Oficialus Telegram kanalas', 'Official Telegram channel'],
  'Сайт PRIVATE DRIVE': ['PRIVATE DRIVE svetainė', 'PRIVATE DRIVE website'],
  'Пользовательское соглашение · проект':
      ['Naudojimo sąlygos · projektas', 'Terms of service · draft'],
  'Политика конфиденциальности · проект':
      ['Privatumo politika · projektas', 'Privacy policy · draft'],
  'Оценка пассажира ещё не получена':
      ['Keleivio įvertinimas dar negautas', 'Passenger rating pending'],
  'Отправить': ['Siųsti', 'Send'],
  'Заказы': ['Užsakymai', 'Bookings'],
  'Карта': ['Žemėlapis', 'Map'],
  'Пилоты': ['Vairuotojai', 'Pilots'],
  'Пассажиры': ['Keleiviai', 'Passengers'],
  'Диспетчер': ['Dispečeris', 'Dispatcher'],
  'Контроль заказов · DEMO': ['Užsakymų valdymas · DEMO', 'Booking management · DEMO'],
  'Назначение только вручную. Локальные тестовые данные.':
      ['Priskiriama tik rankiniu būdu. Vietiniai bandomieji duomenys.',
       'Manual dispatch only. Local demo data.'],
  'Новых тестовых заявок нет': ['Nėra naujų bandomųjų užsakymų', 'No new demo bookings'],
  'Назначить тестового пилота': ['Priskirti bandomąjį vairuotoją', 'Assign demo pilot'],
  'Назначено пилоту · ожидает принятия':
      ['Priskirta vairuotojui · laukiama patvirtinimo', 'Assigned to pilot · awaiting acceptance'],
  'Пилот принял заказ': ['Vairuotojas priėmė užsakymą', 'Pilot accepted booking'],
  'Заказ завершён': ['Užsakymas baigtas', 'Booking completed'],
  'Карта активных пилотов · DEMO': ['Aktyvių vairuotojų žemėlapis · DEMO', 'Active pilots map · DEMO'],
  'Карта · без сетевых тайлов': ['Žemėlapis · neprisijungus', 'Map · offline tiles'],
  'ПИЛОТЫ · DEMO': ['VAIRUOTOJAI · DEMO', 'PILOTS · DEMO'],
  'Тестовый пилот · текущая сессия':
      ['Bandomasis vairuotojas · ši sesija', 'Demo pilot · current session'],
  'ПАССАЖИРЫ · DEMO': ['KELEIVIAI · DEMO', 'PASSENGERS · DEMO'],
  'В текущей сессии пассажирские заявки отсутствуют':
      ['Šioje sesijoje keleivių užsakymų nėra', 'No passenger bookings in this session'],
  'Тестовый пассажир · без персональных данных':
      ['Bandomasis keleivis · be asmens duomenų', 'Demo passenger · no personal data'],
  'Мои заказы · PRIVATE DRIVE': ['Mano užsakymai · PRIVATE DRIVE', 'My bookings · PRIVATE DRIVE'],
  'Заказов в демосессии пока нет':
      ['Šioje demo sesijoje užsakymų dar nėra', 'No bookings in this demo session'],
  'Стоимость по запросу · диспетчер подтвердит цену до оплаты':
      ['Kaina pagal užklausą · dispečeris patvirtins prieš apmokėjimą',
       'Price on request · dispatcher confirms before payment'],
  'Отменить заказ': ['Atšaukti užsakymą', 'Cancel booking'],
  'Отменить заказ?': ['Atšaukti užsakymą?', 'Cancel booking?'],
  'Отменится только тестовая заявка.':
      ['Bus atšauktas tik bandomasis užsakymas.', 'Only the demo booking will be cancelled.'],
  'Оставить заказ': ['Palikti užsakymą', 'Keep booking'],
  'Подтвердить отмену': ['Patvirtinti atšaukimą', 'Confirm cancellation'],
  'Заявка отменена · демо': ['Užsakymas atšauktas · demo', 'Booking cancelled · demo'],
  'Сообщения пилота': ['Vairuotojo žinutės', 'Pilot messages'],
  'Сообщений от пилота пока нет':
      ['Vairuotojo žinučių dar nėra', 'No messages from pilot yet'],
  'Ответить пилоту': ['Atsakyti vairuotojui', 'Reply to pilot'],
  'Локальный чат DEMO: без отправки через интернет.':
      ['Vietinis DEMO pokalbis: žinutės nesiunčiamos internetu.',
       'Local DEMO chat: no messages sent online.'],
  'На линии': ['Prisijungęs', 'Online'],
  'Не на линии': ['Neprisijungęs', 'Offline'],
  'GPS нет': ['GPS nėra', 'No GPS'],
  'GPS доступен': ['GPS veikia', 'GPS available'],
  'Оплата': ['Mokėjimas', 'Payment'],
  'Подача': ['Paėmimas', 'Pickup'],
  'Назначение': ['Tikslas', 'Destination'],
  'Услуги': ['Paslaugos', 'Services'],
  'PRIVATE DRIVE · Пассажир': ['PRIVATE DRIVE · Keleivis', 'PRIVATE DRIVE · Passenger'],
  'Мои заказы': ['Mano užsakymai', 'My bookings'],
  'Контакты и документы': ['Kontaktai ir dokumentai', 'Contacts and documents'],
  'Сообщение от пилота': ['Žinutė nuo vairuotojo', 'Message from pilot'],
  'Тестовый заказ поездки': ['Bandomasis kelionės užsakymas', 'Demo trip booking'],
  'Демонстрация. Не отправляет заказы и не списывает деньги.':
      ['Demonstracija. Užsakymai nesiunčiami, pinigai nenuskaitomi.',
       'Demo only. No orders are sent and no money is charged.'],
  'выбранный тип поездки': ['pasirinktas kelionės tipas', 'selected ride type'],
  'Туда и обратно': ['Pirmyn ir atgal', 'Round trip'],
  'Популярные направления': ['Populiarios kryptys', 'Popular destinations'],
  'Откуда': ['Iš kur', 'From'],
  'Куда': ['Kur', 'To'],
  'Поменять А и Б': ['Sukeisti pradžią ir tikslą', 'Swap pickup and drop-off'],
  'Время': ['Laikas', 'Time'],
  'Дата': ['Data', 'Date'],
  'Личные настройки пассажира для поездки':
      ['Keleivio kelionės nuostatos', 'Passenger ride preferences'],
  'Цветы, кофе, вода, комфорт и пожелания':
      ['Gėlės, kava, vanduo ir pageidavimai', 'Flowers, coffee, water and preferences'],
  'Встреча с табличкой · +15 €': ['Pasitikimas su lentele · +15 €', 'Meet and greet · +€15'],
  'Поездка с животными · цена по запросу':
      ['Kelionė su gyvūnais · kaina pagal užklausą', 'Pets · price on request'],
  'Трезвый водитель · ×2 к тарифу':
      ['Blaivus vairuotojas · ×2 tarifas', 'Designated driver · 2× fare'],
  'Музыка в дорогу · бесплатно':
      ['Muzika kelionei · nemokamai', 'Music for your journey · free'],
  'Цветы · стоимость по запросу': ['Gėlės · kaina pagal užklausą', 'Flowers · price on request'],
  'Кофе · стоимость по запросу': ['Kava · kaina pagal užklausą', 'Coffee · price on request'],
  'Питьевая вода · стоимость уточняется':
      ['Geriamasis vanduo · kaina tikslinama', 'Drinking water · price to confirm'],
  'Тихая поездка · без музыки и разговоров':
      ['Rami kelionė · be muzikos ir pokalbių', 'Quiet ride · no music or conversation'],
  'Помощь с багажом': ['Pagalba su bagažu', 'Luggage assistance'],
  'Комфорт и музыка в дороге': ['Komfortas ir muzika', 'Comfort and music'],
  'Радиостанция · FM-частоты Вильнюса':
      ['Radijo stotis · Vilniaus FM dažniai', 'Radio station · Vilnius FM'],
  'Желаемая температура в салоне':
      ['Pageidaujama salono temperatūra', 'Preferred cabin temperature'],
  'На усмотрение пилота': ['Vairuotojo nuožiūra', "Pilot's choice"],
  'Другие пожелания к поездке': ['Kiti kelionės pageidavimai', 'Other ride requests'],
  'Например, вода без газа, тишина или помощь с багажом':
      ['Pvz., negazuotas vanduo, tyla arba pagalba su bagažu',
       'E.g. still water, quiet ride or help with luggage'],
  'Способ оплаты · только выбор': ['Mokėjimo būdas · tik pasirinkimas', 'Payment method · selection only'],
  'Управление заказом · сообщения': ['Užsakymo valdymas · žinutės', 'Manage booking · messages'],
  'Карта временно недоступна': ['Žemėlapis laikinai nepasiekiamas', 'Map temporarily unavailable'],
  'Повторить загрузку': ['Bandyti dar kartą', 'Retry'],
  'Проверка сервера карты…': ['Tikrinamas žemėlapio serveris…', 'Checking map server…'],
  'Карта · офлайн-тест': ['Žemėlapis · neprisijungus', 'Map · offline test'],
  'Вильнюс — Каунас': ['Vilnius — Kaunas', 'Vilnius — Kaunas'],
  'Аэропорт': ['Oro uostas', 'Airport'],
  'Вильнюс — Варшава': ['Vilnius — Varšuva', 'Vilnius — Warsaw'],
  'Вильнюс — Клайпеда': ['Vilnius — Klaipėda', 'Vilnius — Klaipėda'],
  'Вильнюс — Тракай': ['Vilnius — Trakai', 'Vilnius — Trakai'],
  'Вильнюс — Паланга': ['Vilnius — Palanga', 'Vilnius — Palanga'],
  'Выбери тип поездки': ['Pasirink kelionės tipą', 'Choose ride type'],
  'Пассажир': ['Keleivis', 'Passenger'],
  'Такси': ['Taksi', 'Taxi'],
  'Трансфер': ['Pervežimas', 'Transfer'],
  'Поездка по городу и другие направления':
      ['Kelionės mieste ir kitomis kryptimis', 'City rides and other destinations'],
  'Междугородние поездки и аэропорты':
      ['Tarpmiestiniai pervežimai ir oro uostai', 'Intercity rides and airports'],
  'Тестовый режим. Реальные заказы и оплата выключены.':
      ['Bandomasis režimas. Tikri užsakymai ir mokėjimai išjungti.',
       'Demo mode. Real bookings and payments are disabled.'],
  'Выбери тестовый интерфейс':
      ['Pasirink bandomąją sąsają', 'Choose demo interface'],
  'Кабина пилота': ['Vairuotojo kabina', 'Pilot cockpit'],
  'КАБИНЕТ ПИЛОТА': ['VAIRUOTOJO KABINA', 'PILOT COCKPIT'],
  'На линии · демо': ['Prisijungęs · demo', 'Online · demo'],
  'Не на линии · демо': ['Neprisijungęs · demo', 'Offline · demo'],
  'ВЫЙТИ НА ЛИНИЮ': ['PRISIJUNGTI', 'GO ONLINE'],
  'УЙТИ С ЛИНИИ': ['ATSIJUNGTI', 'GO OFFLINE'],
  'Открыть карту': ['Atidaryti žemėlapį', 'Open map'],
  'Мои заказы · управление': ['Mano užsakymai · valdymas', 'My bookings · manage'],
  'Кабинет диспетчера · демо': ['Dispečerio kabinetas · demo', 'Dispatcher console · demo'],
  'Тестовая связь между устройствами':
      ['Bandomasis ryšys tarp įrenginių', 'Test device synchronization'],
  'О компании · Контакты · Соглашение':
      ['Apie įmonę · Kontaktai · Sąlygos', 'About · Contacts · Terms'],
  'Тестовые заявки сохраняются на этом устройстве. Нет реальных заказов, платежей и сервера.':
      ['Bandomieji užsakymai saugomi šiame įrenginyje. Tikrų užsakymų, mokėjimų ir serverio nėra.',
       'Demo bookings stay on this device. No real bookings, payments or server.'],
  'Тестовый режим. Статус линии не отправляется на сервер.':
      ['Bandomasis režimas. Būsena nesiunčiama į serverį.',
       'Demo mode. Online status is not sent to the server.'],
  'Waze': ['Waze', 'Waze'],
  'Ночная карта': ['Naktinis žemėlapis', 'Night map'],
  'Дневная карта': ['Dieninis žemėlapis', 'Day map'],
  'Поездка завершена · демо': ['Kelionė baigta · demo', 'Trip completed · demo'],
  'Нет назначенной поездки': ['Nėra priskirtos kelionės', 'No assigned trip'],
  'Остановка': ['Sustojimas', 'Stop'],
  'Выбери язык': ['Pasirink kalbą', 'Choose language'],
};
