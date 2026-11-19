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
      if (stored == 'RU' || stored == 'LT' || stored == 'EN') {
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
