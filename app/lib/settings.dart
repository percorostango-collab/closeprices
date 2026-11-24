import 'dart:math';
import 'package:shared_preferences/shared_preferences.dart';

/// Impostazioni dell'app: indirizzo del server e un identificativo anonimo per le correzioni.
class AppSettings {
  static const _kServer = 'server_url';
  static const _kUser = 'user_id';

  static Future<String> serverUrl() async =>
      (await SharedPreferences.getInstance()).getString(_kServer) ?? '';

  static Future<void> setServerUrl(String v) async =>
      (await SharedPreferences.getInstance()).setString(_kServer, v.trim());

  /// Identificativo casuale, generato una volta sola. Non contiene dati personali.
  static Future<String> userId() async {
    final p = await SharedPreferences.getInstance();
    var id = p.getString(_kUser);
    if (id == null) {
      final r = Random.secure();
      id = List.generate(24, (_) => r.nextInt(16).toRadixString(16)).join();
      await p.setString(_kUser, id);
    }
    return id;
  }
}
