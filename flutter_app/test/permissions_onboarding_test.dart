import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:private_drive/permissions_onboarding.dart';

class FakePermissions implements PdPermissionGateway {
  PermissionStatus notifications = PermissionStatus.denied;
  PermissionStatus location = PermissionStatus.denied;
  int notificationRequests = 0;
  int locationRequests = 0;
  int systemOpens = 0;
  @override
  Future<PermissionStatus> notificationStatus() async => notifications;
  @override
  Future<PermissionStatus> locationStatus() async => location;
  @override
  Future<PermissionStatus> requestNotifications() async {
    notificationRequests++;
    return notifications;
  }
  @override
  Future<PermissionStatus> requestLocation() async {
    locationRequests++;
    return location;
  }
  @override
  Future<bool> openSettings() async {
    systemOpens++;
    return true;
  }
}

void main() {
  testWidgets('First launch asks permission only after user interaction',
      (tester) async {
    final gateway = FakePermissions();
    var saved = false;
    Future<bool> read() async => saved;
    Future<void> save() async { saved = true; }

    await tester.pumpWidget(MaterialApp(
      home: PdPermissionsFirstLaunch(
        gateway: gateway,
        readCompleted: read,
        writeCompleted: save,
        child: const Scaffold(body: Text('Вход PRIVATE DRIVE')),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('permission-onboarding-allow')), findsOneWidget);
    expect(gateway.notificationRequests, 0);
    expect(gateway.locationRequests, 0);

    await tester.tap(find.byKey(const Key('permission-onboarding-allow')));
    await tester.pumpAndSettle();
    expect(gateway.notificationRequests, 1);
    expect(gateway.locationRequests, 1);
    expect(saved, isTrue);
    expect(find.text('Вход PRIVATE DRIVE'), findsOneWidget);
  });

  testWidgets('Declining optional permissions never blocks sign-in or asks OS',
      (tester) async {
    final gateway = FakePermissions();
    var completed = false;
    Future<bool> read() async => completed;
    Future<void> write() async { completed = true; }

    Widget gate() => MaterialApp(
      home: PdPermissionsFirstLaunch(
        gateway: gateway,
        readCompleted: read,
        writeCompleted: write,
        child: const Scaffold(body: Text('Вход PRIVATE DRIVE')),
      ),
    );
    await tester.pumpWidget(gate());
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('permission-onboarding-skip')));
    await tester.pumpAndSettle();
    expect(find.text('Вход PRIVATE DRIVE'), findsOneWidget);
    expect(completed, isTrue);
    expect(gateway.notificationRequests, 0);
    expect(gateway.locationRequests, 0);

    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(gate());
    await tester.pumpAndSettle();
    expect(find.text('Вход PRIVATE DRIVE'), findsOneWidget);
    expect(find.byKey(const Key('permission-onboarding-allow')), findsNothing);
  });

  testWidgets('Denied permissions can be requested from app settings',
      (tester) async {
    final gateway = FakePermissions();
    await tester.pumpWidget(MaterialApp(
      home: PdPermissionSettingsPage(gateway: gateway),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Не разрешено'), findsNWidgets(2));
    await tester.tap(find.descendant(
      of: find.byKey(const Key('permission-settings-notifications')),
      matching: find.text('Настроить'),
    ));
    await tester.pumpAndSettle();
    expect(gateway.notificationRequests, 1);
    await tester.tap(find.byKey(const Key('permission-open-system-settings')));
    await tester.pump();
    expect(gateway.systemOpens, 1);
  });

  testWidgets('Permanently denied location opens system settings',
      (tester) async {
    final gateway = FakePermissions()
      ..location = PermissionStatus.permanentlyDenied;
    await tester.pumpWidget(MaterialApp(
      home: PdPermissionSettingsPage(gateway: gateway),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(
      of: find.byKey(const Key('permission-settings-location')),
      matching: find.text('Настроить'),
    ));
    await tester.pumpAndSettle();
    expect(gateway.locationRequests, 0);
    expect(gateway.systemOpens, 1);
  });
}
