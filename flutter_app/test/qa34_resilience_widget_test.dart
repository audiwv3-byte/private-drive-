import '../lib/qa_pilot_transport.dart';
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
class FakeApi extends QaPilotOrdersApi {
  FakeApi(this.server):super(baseUrl:QaPilotOrdersApi.stage,token:'synthetic-test-token-never-sent-to-network');
  final Server server;
  bool offline=false;
  bool loseAck=false;
  @override
  Future<List<PilotAssignedOrder>> load() async { if(offline) throw StateError('offline'); return server.read(); }
  @override
  Future<Map<String,dynamic>> action(String orderId,String action) async {
    expect(orderId,id);
    if(offline) throw StateError('offline');
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
    if(loseAck){loseAck=false;throw StateError('ack lost');}
    return {'order_id':id,'status':server.status,'payment_mode':'disabled'};
  }
}
void main(){
  testWidgets('lost acknowledgement, offline refresh and reconnection restore server timer', (tester) async {
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final server=Server()..status='underway';
    final api=FakeApi(server);
    final control=find.byKey(const ValueKey('pilot-trip-control-$id'));
    final refresh=find.byKey(const Key('pilot-server-orders-refresh'));
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:PilotAssignedOrdersPanel(api:api))));
    await tester.pumpAndSettle();
    await tester.ensureVisible(control);
    await tester.tap(control);
    await tester.pumpAndSettle();
    api.loseAck=true;
    await tester.tap(find.text('Остановка'));
    await tester.pumpAndSettle();
    expect(server.waiting,true);
    api.offline=true;
    await tester.ensureVisible(refresh);
    await tester.tap(refresh);
    await tester.pumpAndSettle();
    expect(control,findsNothing);
    server.seconds=61;
    server.cents=50;
    api.offline=false;
    await tester.tap(refresh);
    await tester.pumpAndSettle();
    expect(find.text('Продолжить поездку'),findsOneWidget);
    expect(find.textContaining('61 сек'),findsOneWidget);
    expect(find.textContaining('0.50'),findsOneWidget);
    expect(server.actions,['stop_start']);
    await tester.ensureVisible(control);
    await tester.tap(control);
    await tester.pumpAndSettle();
    expect(server.waiting,false);
    expect(server.actions,['stop_start','stop_end']);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
