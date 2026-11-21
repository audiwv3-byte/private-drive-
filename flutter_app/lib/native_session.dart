class PdNativeSession {
  const PdNativeSession({required this.token, required this.userId,
    required this.role, required this.expiresAt});
  final String token;
  final String userId;
  final String role;
  final DateTime expiresAt;
  bool get active => DateTime.now().isBefore(expiresAt);
  bool get canPilot => const {'admin', 'pilot', 'pilot_dispatcher'}.contains(role);
  bool get canDispatch => const {'admin', 'dispatcher', 'pilot_dispatcher'}.contains(role);
}
