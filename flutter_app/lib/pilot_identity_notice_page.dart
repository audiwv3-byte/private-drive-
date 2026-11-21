import 'package:flutter/material.dart';

import 'pilot_identity_check_page.dart';

/// Pre-camera information screen. No capture, uploads, identity decisions,
/// consent records, SMS or network access. Only a local acknowledgement.
class PdPilotIdentityNoticePage extends StatefulWidget {
  const PdPilotIdentityNoticePage({
    super.key,
    this.cameraPermission = const PdSystemPilotCameraPermission(),
  });

  final PdPilotCameraPermission cameraPermission;

  @override
  State<PdPilotIdentityNoticePage> createState() =>
      _PdPilotIdentityNoticePageState();
}

class _PdPilotIdentityNoticePageState extends State<PdPilotIdentityNoticePage> {
  String _language = 'RU';
  bool _acknowledged = false;

  String _tr(String ru, String lt, String en) {
    if (_language == 'LT') return lt;
    if (_language == 'EN') return en;
    return ru;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text(_tr('Перед проверкой личности',
              'Prieš tapatybės patikrą', 'Before identity verification')),
          actions: [
            DropdownButton<String>(
              key: const Key('pilot-identity-notice-language'),
              value: _language,
              dropdownColor: Theme.of(context).colorScheme.surface,
              underline: const SizedBox.shrink(),
              items: const [
                DropdownMenuItem(value: 'RU', child: Text('RU')),
                DropdownMenuItem(value: 'LT', child: Text('LT')),
                DropdownMenuItem(value: 'EN', child: Text('EN')),
              ],
              onChanged: (value) {
                if (value != null) {
                  setState(() {
                    _language = value;
                    _acknowledged = false;
                  });
                }
              },
            ),
            const SizedBox(width: 12),
          ],
        ),
        body: SafeArea(
          child: ListView(
            key: const Key('pilot-identity-notice-page'),
            padding: const EdgeInsets.all(24),
            children: [
              Text(
                _tr('Проверка личности пилота · тест',
                    'Vairuotojo tapatybės patikra · bandymas',
                    'Pilot identity verification · test'),
                style: const TextStyle(
                    fontSize: 22, fontWeight: FontWeight.bold),
                key: const Key('pilot-identity-notice-title'),
              ),
              const SizedBox(height: 16),
              Text(
                _tr(
                  'Цель будущей проверки — убедиться, что поездку выполняет '
                      'одобренный пилот. Планируется проверка при подключении '
                      'и затем не реже одного раза в 7 дней.',
                  'Būsimos patikros tikslas – įsitikinti, kad kelionę vykdo '
                      'patvirtintas vairuotojas. Planuojama tikrinti '
                      'registruojantis ir vėliau bent kartą per 7 dienas.',
                  'The planned check aims to confirm that an approved pilot '
                      'performs the trip. A check is planned at onboarding '
                      'and at least once every 7 days thereafter.',
                ),
                key: const Key('pilot-identity-notice-purpose'),
              ),
              const SizedBox(height: 12),
              Text(
                _tr(
                  'В будущем может потребоваться один снимок лица. '
                      'Сейчас камера используется только для проверки '
                      'разрешения: фото и видео не создаются, не сохраняются '
                      'и не отправляются. Микрофон и распознавание лица '
                      'не используются.',
                  'Ateityje gali reikėti vienos veido nuotraukos. '
                      'Šiuo metu tikrinamas tik kameros leidimas: '
                      'nuotraukos ir vaizdo įrašai nekuriami, '
                      'nesaugomi ir nesiunčiami. Mikrofonas ir '
                      'veido atpažinimas nenaudojami.',
                  'A single face photo may be needed in the future. '
                      'At present, only camera permission is tested: '
                      'no photo or video is captured, stored or sent. '
                      'The microphone and facial recognition are not used.',
                ),
                key: const Key('pilot-identity-notice-data'),
              ),
              const SizedBox(height: 12),
              Text(
                _tr(
                  'В будущем снимок сможет просматривать только '
                      'уполномоченный проверяющий. Защищённая передача, '
                      'хранение, сроки удаления и порядок обжалования '
                      'пока не утверждены и не подключены. '
                      'До их утверждения фотографии не собираются.',
                  'Ateityje nuotrauką galės peržiūrėti tik įgaliotas '
                      'tikrintojas. Saugus perdavimas, saugojimas, '
                      'ištrynimo terminai ir apskundimo tvarka dar '
                      'nepatvirtinti ir neįdiegti. Kol kas nuotraukos '
                      'nerenkamos.',
                  'In the future, only an authorized reviewer may view '
                      'the photo. Secure transfer, storage, deletion '
                      'periods and appeals are not yet approved or enabled. '
                      'No photos are collected until these are approved.',
                ),
                key: const Key('pilot-identity-notice-retention'),
              ),
              const SizedBox(height: 12),
              Text(
                _tr(
                  'Ты можешь отказаться от доступа к камере. '
                      'Сейчас отказ не ограничивает заказы: '
                      'подтверждение личности не работает. '
                      'В будущем должна быть предусмотрена связь '
                      'с администратором и альтернативная проверка.',
                  'Galite nesuteikti kameros leidimo. Dabar atsisakymas '
                      'neriboja užsakymų, nes tapatybės patikra neveikia. '
                      'Ateityje turi būti numatyta galimybė kreiptis į '
                      'administratorių ir alternatyvi patikra.',
                  'You may deny camera access. Currently, denial does '
                      'not restrict bookings because identity verification '
                      'is not active. A contact and alternative review '
                      'process must be provided before future activation.',
                ),
                key: const Key('pilot-identity-notice-rights'),
              ),
              const SizedBox(height: 12),
              SelectableText(
                _tr(
                  'По вопросам обработки данных и прав GDPR: '
                      'eurobaltictransfer@gmail.com.',
                  'Dėl duomenų tvarkymo ir BDAR teisių: '
                      'eurobaltictransfer@gmail.com.',
                  'For data handling and GDPR rights: '
                      'eurobaltictransfer@gmail.com.',
                ),
                key: const Key('pilot-identity-notice-contact'),
              ),
              const SizedBox(height: 20),
              CheckboxListTile(
                key: const Key('pilot-identity-notice-acknowledge'),
                value: _acknowledged,
                controlAffinity: ListTileControlAffinity.leading,
                onChanged: (value) =>
                    setState(() => _acknowledged = value ?? false),
                title: Text(_tr(
                  'Я прочитал информацию о тестовом экране. '
                      'Это не согласие на сбор фотографий.',
                  'Susipažinau su informacija apie bandomąjį ekraną. '
                      'Tai nėra sutikimas rinkti nuotraukas.',
                  'I have read the test screen information. '
                      'This is not consent to collect photos.',
                )),
              ),
              const SizedBox(height: 8),
              FilledButton(
                key: const Key('pilot-identity-notice-continue'),
                onPressed: _acknowledged
                    ? () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => PdPilotIdentityCheckPage(
                              cameraPermission: widget.cameraPermission,
                            ),
                          ),
                        )
                    : null,
                child: Text(_tr('Продолжить к проверке разрешения',
                    'Tęsti kameros leidimo patikrą',
                    'Continue to camera permission test')),
              ),
            ],
          ),
        ),
      );
}
