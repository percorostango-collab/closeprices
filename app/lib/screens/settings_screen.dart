import 'package:flutter/material.dart';
import '../api.dart';
import '../settings.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _url = TextEditingController();
  String? _status;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    AppSettings.serverUrl().then((v) {
      if (mounted) setState(() => _url.text = v);
    });
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _status = null;
    });
    final url = _url.text.trim();
    await AppSettings.setServerUrl(url);
    if (url.isEmpty) {
      setState(() {
        _busy = false;
        _status = 'Indirizzo vuoto: l\'app non può funzionare.';
      });
      return;
    }
    try {
      // prova reale: una scansione di un codice qualsiasi valido
      await PvApi(url).scan('8008490000021');
      if (mounted) setState(() => _status = 'Server raggiunto: tutto a posto.');
    } on ApiException catch (e) {
      if (mounted) setState(() => _status = 'Non funziona: ${e.message}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Impostazioni')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          const Text('Indirizzo del servizio Prezzi Vicini', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          TextField(
            controller: _url,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              hintText: 'https://il-tuo-server.example',
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Controllo…' : 'Salva e prova')),
          if (_status != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_status!)),
          const SizedBox(height: 24),
          const Text(
            'Come funziona: l\'app manda al servizio il codice a barre e la tua posizione approssimativa; il servizio '
            'risponde con ciò che ha verificato. Dove non ha una prova lo dice: non fa ipotesi.',
          ),
        ]),
      );
}
