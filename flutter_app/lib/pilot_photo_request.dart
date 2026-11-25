import 'dart:async';

import 'package:flutter/material.dart';

import 'pilot_identity_api.dart';
import 'pilot_identity_notice_page.dart';

/// Surface a dispatcher request without interrupting entry into the cabin.
class PdPilotPhotoRequest extends StatefulWidget {
  const PdPilotPhotoRequest({super.key, required this.api});

  final PdIdentityApi api;

  @override
  State<PdPilotPhotoRequest> createState() => _PdPilotPhotoRequestState();
}

class _PdPilotPhotoRequestState extends State<PdPilotPhotoRequest> {
  Timer? _poll;
  bool _requested = false;
  bool _loading = false;
  bool _opened = false;

  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => _refresh());
  }

  Future<void> _refresh() async {
    if (_loading || _opened) return;
    _loading = true;
    try {
      final status = await widget.api.status();
      if (mounted) setState(() => _requested = status['requested'] == true);
    } catch (_) {
      // A failed refresh must not interrupt the pilot's map or shift.
    } finally {
      _loading = false;
    }
  }

  Future<void> _open() async {
    _opened = true;
    await Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => PdPilotIdentityNoticePage(api: widget.api),
    ));
    _opened = false;
    if (mounted) await _refresh();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => !_requested
      ? const SizedBox.shrink()
      : FilledButton.tonalIcon(
          key: const Key('pilot-open-identity-check'),
          onPressed: _open,
          icon: const Icon(Icons.verified_user_outlined),
          label: const Text('Требуется фотопроверка'),
        );
}
