import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_language.dart';

class PassengerProfilePage extends StatefulWidget {
  const PassengerProfilePage({super.key, required this.storageScope});

  final String storageScope;

  @override
  State<PassengerProfilePage> createState() => _PassengerProfilePageState();
}

class _PassengerProfilePageState extends State<PassengerProfilePage> {
  static const _avatars = [
    Icons.person_outline,
    Icons.face_3_outlined,
    Icons.face_6_outlined,
    Icons.pets_outlined,
  ];
  final _preferences = SharedPreferencesAsync();
  int _avatar = 0;
  Uint8List? _photo;
  bool _busy = true;
  String get _key => 'pd_passenger_avatar_v1.${widget.storageScope}';

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    try {
      final value = await _preferences.getString(_key);
      if (value != null && mounted) {
        final avatar = int.tryParse(value);
        if (avatar != null && avatar >= 0 && avatar < _avatars.length) {
          _avatar = avatar;
        } else if (value.startsWith('photo:')) {
          _photo = base64Decode(value.substring(6));
        }
      }
    } catch (_) {
      _photo = null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save({int? avatar}) async {
    setState(() => _busy = true);
    try {
      Uint8List? photo;
      if (avatar == null) {
        final file = await ImagePicker().pickImage(
          source: ImageSource.gallery,
          maxWidth: 512,
          maxHeight: 512,
          imageQuality: 75,
          requestFullMetadata: false,
        );
        if (!mounted || file == null) return;
        if (await file.length() > 512 * 1024) {
          throw const FormatException('Profile image exceeds storage limit');
        }
        photo = await file.readAsBytes();
        if (photo.isEmpty || photo.length > 512 * 1024) {
          throw const FormatException('Invalid profile image');
        }
        final image = await decodeImageFromList(photo);
        image.dispose();
      }
      if (!mounted) return;
      await _preferences.setString(_key,
        photo == null ? avatar.toString() : 'photo:${base64Encode(photo)}');
      if (!mounted) return;
      setState(() {
        _photo = photo;
        if (avatar != null) _avatar = avatar;
      });
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(
          pdTr(context, 'Не удалось сохранить аватар',
            'Nepavyko išsaugoti avataro', 'Could not save your avatar'),
        )));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(pdTr(context, 'Профиль', 'Profilis', 'Profile'))),
    body: SafeArea(child: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Center(child: CircleAvatar(
          radius: 56,
          foregroundImage: _photo == null ? null : MemoryImage(_photo!),
          child: Icon(_avatars[_avatar], size: 48),
        )),
        const SizedBox(height: 24),
        Center(child: Wrap(
          spacing: 8,
          children: [
            for (var i = 0; i < _avatars.length; i++)
              IconButton.filledTonal(
                isSelected: _photo == null && _avatar == i,
                tooltip: '${pdTr(context, 'Аватар', 'Avataras', 'Avatar')} ${i + 1}',
                icon: Icon(_avatars[i]),
                onPressed: _busy ? null : () => _save(avatar: i),
              ),
          ],
        )),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: _busy ? null : () => _save(),
          icon: const Icon(Icons.photo_library_outlined),
          label: Text(pdTr(context, 'Загрузить фото',
            'Įkelti nuotrauką', 'Upload a photo')),
        ),
      ],
    )),
  );
}
