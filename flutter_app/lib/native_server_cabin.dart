import 'package:flutter/material.dart';
import 'app_language.dart';
import 'native_orders_api.dart';
import 'native_pilot_orders.dart';
import 'passenger_ride_entry.dart';
import 'pilot_cabin.dart';

/// Authenticated entry never constructs or restores a local trip store.
class NativeServerCabin extends StatelessWidget {
  const NativeServerCabin({super.key, this.ordersApi, this.pilotApi,
    this.onSignOut, this.onBackToCabinets, this.enableMapTiles = true})
    : assert((ordersApi == null) != (pilotApi == null));
  final NativeOrdersApi? ordersApi;
  final NativePilotOrdersApi? pilotApi;
  final VoidCallback? onSignOut, onBackToCabinets;
  final bool enableMapTiles;

  @override
  Widget build(BuildContext context) {
    final passenger = ordersApi;
    if (passenger != null) {
      return PdPassengerLanguageScope(child: PassengerRideEntry(
        ordersApi: passenger, tripStore: null, enableMapTiles: enableMapTiles,
        onSignOut: onSignOut, onBackToCabinets: onBackToCabinets));
    }
    return PilotCabin(assignmentApi: pilotApi!, enableMapTiles: enableMapTiles,
      onSignOut: onSignOut, onBackToCabinets: onBackToCabinets);
  }
}
