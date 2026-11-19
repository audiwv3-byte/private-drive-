import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One language selection shared across all native Android demo routes.
/// A missing translation stays visible in Russian rather than disappearing.
class PdLanguage extends ChangeNotifier {
  String _value = 'RU';
  String get value => _value;
  static const _storageKey = 'pd_native_language_v1';

  Future<void> restore() async {
    try {
      final stored = await SharedPreferencesAsync().getString(_storageKey);
      if (stored != null && (stored == 'RU' || stored == 'LT' || stored == 'EN')) {
        set(stored, persist: false);
      }
    } catch (_) {
      // Offline preview also runs in widget tests without platform storage.
    }
  }

  void set(String language, {bool persist = true}) {
    if (language != 'RU' && language != 'LT' && language != 'EN') return;
    if (_value == language) return;
    _value = language;
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

String pdTr(BuildContext context, String ru, String lt, String en) {
  final language = PdLanguageScope.of(context).value;
  return language == 'LT' ? lt : language == 'EN' ? en : ru;
}

/// Common UI labels used across pilot, passenger and dispatcher routes.
/// The business identifiers and fare-routing strings remain in Russian.
String pdLabel(BuildContext context, String ru) {
  final language = PdLanguageScope.of(context).value;
  if (language == 'RU') return ru;
  final translations = _labels[ru];
  if (translations == null) return ru;
  return language == 'LT' ? translations[0] : translations[1];
}

const Map<String, List<String>> _labels = {
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
