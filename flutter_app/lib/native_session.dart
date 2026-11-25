class PdNativeSession {
  const PdNativeSession({required this.token, required this.userId,
    required this.role, required this.expiresAt});
  final String token;
  final String userId;
  final String role;
  final DateTime expiresAt;

  factory PdNativeSession.fromApi(Map<String, dynamic> result, {String? savedToken}) {
    final token = savedToken ?? result['access_token'];
    final userId = result['user_id'];
    final expiresIn = result['expires_in'];
    final role = result['role'];
    if (result['verified'] != true ||
        token is! String || token.length < 40 || token.length > 256 ||
        userId is! String || userId.isEmpty ||
        result['token_type'] != 'Bearer' ||
        role is! String ||
        !const {'passenger', 'admin', 'pilot', 'dispatcher', 'pilot_dispatcher'}.contains(role) ||
        expiresIn is! int || expiresIn <= 0) {
      throw const FormatException('Сервер не выдал корректную сессию.');
    }
    return PdNativeSession(token: token, userId: userId, role: role,
      expiresAt: DateTime.now().add(Duration(seconds: expiresIn)));
  }
  bool get active => DateTime.now().isBefore(expiresAt);
  bool get canPilot => const {'admin', 'pilot', 'pilot_dispatcher'}.contains(role);
  bool get canDispatch => const {'admin', 'dispatcher', 'pilot_dispatcher'}.contains(role);
}
