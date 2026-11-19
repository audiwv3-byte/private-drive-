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
