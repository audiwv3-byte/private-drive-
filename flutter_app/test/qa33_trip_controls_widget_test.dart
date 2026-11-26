import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../lib/native_pilot_orders.dart';

const id='05cdbc84-0930-4c52-baa1-149a03190d78';
class Server {
  String status='assigned';
  bool waiting=false;
  int seconds=0, cents=0;
  final actions=<String>[];
  List<PilotAssignedOrder> read()=>status=='finished'?[]:[
    PilotAssignedOrder.parse({
      'order_id':id,'from':'Synthetic A','to':'Synthetic B',
      'trip_date':'2027-01-01','trip_time':'12:00','status':status,
      'waiting_seconds':seconds,'waiting_active':waiting,'stop_charge_cents':cents
    })
  ];
}
class FakeApi extends NativePilotOrdersApi {
  FakeApi(this.server):super(baseUrl:NativePilotOrdersApi.stage,token:'synthetic-test-token-never-sent-to-network');
  final Server server;
  @override
  Future<List<PilotAssignedOrder>> load() async =>server.read();
  @override
  Future<Map<String,dynamic>> action(String orderId,String action) async {
    expect(orderId,id);
    server.actions.add(action);
    switch(action){
      case 'approach': server.status='approaching'; break;
      case 'arrive': server.status='arrived'; break;
      case 'start': server.status='underway'; break;
      case 'stop_start': server.waiting=true; break;
      case 'stop_end': server.waiting=false; break;
      case 'finish': server.status='finished'; break;
      default: fail('unexpected action');
    }
    return {'order_id':id,'status':server.status,'payment_mode':'disabled'};
  }
}
void main(){
  testWidgets('one trip control and restoration of active server stop', (tester) async {
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final server=Server();
    final control=find.byKey(const ValueKey('pilot-trip-control-$id'));
    Future<void> mount() async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:PilotAssignedOrdersPanel(api:FakeApi(server)))));
      await tester.pumpAndSettle();
    }
    Future<void> press(String label) async {
      expect(control,findsOneWidget);
      expect(find.descendant(of:control,matching:find.text(label)),findsOneWidget);
      await tester.ensureVisible(control);
      await tester.tap(control);
      await tester.pumpAndSettle();
    }
    await mount();
    await press('К пассажиру');
    await press('На месте');
    await press('В путь');
    await press('Управление поездкой');
    await tester.tap(find.text('Остановка'));
    await tester.pumpAndSettle();
    expect(server.waiting,true);
    server.seconds=61;
    server.cents=50;
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await mount();
    expect(find.textContaining('61 сек'),findsOneWidget);
    expect(find.textContaining('0.50'),findsOneWidget);
    expect(server.actions.where((x)=>x=='stop_start').length,1);
    await press('Продолжить поездку');
    await press('Управление поездкой');
    await tester.tap(find.text('Завершить поездку'));
    await tester.pumpAndSettle();
    expect(find.text('Назначенных заказов нет.'),findsOneWidget);
    expect(server.actions,['approach','arrive','start','stop_start','stop_end','finish']);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
