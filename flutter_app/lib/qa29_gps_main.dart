import 'qa_pilot_transport.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'native_pilot_orders.dart';

// This entry point is not main.dart. No real login, payment, SMS or live API.
const qa29Token = 'qa29-synthetic-pilot-session-not-a-real-credential';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final allowed = kDebugMode && !kIsWeb &&
      defaultTargetPlatform == TargetPlatform.android &&
      QaPilotOrdersApi.qa29Loopback;
  runApp(MaterialApp(
    title: 'PRIVATE DRIVE GPS QA29',
    home: Scaffold(
      appBar: AppBar(title: const Text('PRIVATE DRIVE GPS QA29')),
      body: allowed
          ? const PilotAssignedOrdersPanel(api: QaPilotOrdersApi(
              baseUrl: QaPilotOrdersApi.qa29Base, token: qa29Token))
          : const Center(child: Text('Изолированный Android QA29 недоступен')),
    ),
  ));
}
