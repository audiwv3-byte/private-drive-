import 'package:flutter/material.dart';
import 'pilot_identity_check_page.dart';
import 'pilot_identity_api.dart';
import 'pilot_photo_capture.dart';

class PdPilotIdentityNoticePage extends StatefulWidget {
  const PdPilotIdentityNoticePage({super.key,
    this.cameraPermission = const PdSystemPilotCameraPermission(),
    this.photoCapture = const PdSystemPilotPhotoCapture(),
    this.api, this.onContinueWithoutVerification});
  final PdPilotCameraPermission cameraPermission;
  final PdPilotPhotoCapture photoCapture;
  final PdIdentityApi? api;
  final VoidCallback? onContinueWithoutVerification;
  @override
  State<PdPilotIdentityNoticePage> createState() => _PdPilotIdentityNoticePageState();
}
class _PdPilotIdentityNoticePageState extends State<PdPilotIdentityNoticePage> {
  String _language = 'RU';
  bool _acknowledged = false;
  String tr(String ru, String lt, String en) => _language == 'LT' ? lt : _language == 'EN' ? en : ru;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('PRIVATE DRIVE · Фотоконтроль'), actions: [
      DropdownButton<String>(
        key: const Key('pilot-identity-notice-language'),
        value: _language,
        items: [for (final code in ['RU', 'LT', 'EN']) DropdownMenuItem(value: code, child: Text(code))],
        onChanged: (value) { if (value != null) setState(() { _language = value; _acknowledged = false; }); },
      ),
    ]),
    body: SafeArea(child: ListView(
      key: const Key('pilot-identity-notice-page'),
      padding: const EdgeInsets.all(24),
      children: [
        Text(tr('Проверка личности пилота', 'Vairuotojo tapatybės patikra', 'Pilot identity verification'),
          key: const Key('pilot-identity-notice-title'),
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
        if (const bool.fromEnvironment('PD_INTERNAL_QA') && widget.onContinueWithoutVerification != null) ...[
          OutlinedButton.icon(
            key: const Key('pilot-identity-notice-qa-skip'),
            onPressed: widget.onContinueWithoutVerification,
            icon: const Icon(Icons.arrow_forward),
            label: const Text('Продолжить без проверки лица')),
          const Text('Только внутренняя тестовая сборка. Личность не подтверждена; права не изменяются.'),
        ],
        const SizedBox(height: 16),
        Text(tr('Цель — подтвердить, что поездку выполняет одобренный пилот. '
          'Решение принимает диспетчер. Проверка действует 7 дней и не назначает роли.',
          'Tikslas – patvirtinti vairuotojo tapatybę. Sprendžia dispečeris. Patikra galioja 7 dienas ir nekeičia teisių.',
          'An authorized reviewer checks the pilot identity. Approval lasts 7 days and never grants roles.'),
          key: const Key('pilot-identity-notice-purpose')),
        const SizedBox(height: 12),
        Text(tr('По нажатию откроется камера для одного снимка лица. '
          'После съёмки можно переснять или отдельно отправить фото. '
          'Нет автоматической отправки, распознавания лица, видео и микрофона.',
          'Kamera padarys vieną veido nuotrauką. Galėsite pakartoti arba atskirai išsiųsti. '
          'Nėra automatinio siuntimo, veido atpažinimo, vaizdo įrašo ar mikrofono.',
          'Take one face photo, preview it and choose whether to send it. '
          'No automatic upload, face matching, video or microphone.'),
          key: const Key('pilot-identity-notice-data')),
        const SizedBox(height: 12),
        Text(tr('Фото доступно только уполномоченному диспетчеру через защищённый сервер. '
          'После решения снимок удаляется. Через 72 часа доступ закрывается; '
          'просроченные снимки удаляются при работе сервера. '
          'История статуса содержит ID заявки и время решения без фотографии.',
          'Nuotrauką mato tik įgaliotas tikrintojas. Po sprendimo ji ištrinama. Prieiga uždaroma po 72 valandų; nuotrauka išvaloma serveriui veikiant.',
          'Only an authorized reviewer can access the photo. It is deleted after a decision. Access expires after 72 hours; cleanup runs while the server is active. '
          'Status history contains no photo.'),
          key: const Key('pilot-identity-notice-retention')),
        const SizedBox(height: 12),
        Text(tr('Можно отказаться от камеры и вернуться в кабинет. '
          'Для альтернативной проверки и обжалования свяжись с администратором. '
          'Снимок сам по себе не подтверждает личность.',
          'Galite atsisakyti ir grįžti. Dėl alternatyvios patikros ar skundo kreipkitės į administratorių.',
          'You may decline and return to your cabin. Contact the administrator for an alternative check or appeal. '
          'Taking a photo does not itself verify identity.'),
          key: const Key('pilot-identity-notice-rights')),
        const SizedBox(height: 12),
        const SelectableText('eurobaltictransfer@gmail.com', key: Key('pilot-identity-notice-contact')),
        CheckboxListTile(
          key: const Key('pilot-identity-notice-acknowledge'),
          value: _acknowledged,
          onChanged: (value) => setState(() => _acknowledged = value ?? false),
          title: Text(tr('Я прочитал информацию о фотоконтроле', 'Susipažinau su informacija', 'I have read the photo check information'))),
        FilledButton(
          key: const Key('pilot-identity-notice-continue'),
          onPressed: !_acknowledged ? null : () => Navigator.push(context, MaterialPageRoute<void>(
            builder: (_) => PdPilotIdentityCheckPage(
              cameraPermission: widget.cameraPermission, photoCapture: widget.photoCapture, api: widget.api,
              onContinueWithoutVerification: widget.onContinueWithoutVerification))),
          child: Text(tr('Продолжить к съёмке', 'Tęsti', 'Continue to camera'))),
        TextButton(onPressed: () => Navigator.maybePop(context), child: Text(tr('Вернуться в кабинет', 'Grįžti', 'Return to cabin'))),
      ],
    )),
  );
}

