import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../gtin.dart';
import '../settings.dart';
import 'result_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _scanner = MobileScannerController(
    formats: const [BarcodeFormat.ean13, BarcodeFormat.ean8, BarcodeFormat.upcA],
  );
  final _manual = TextEditingController();
  double _radiusKm = 10;
  bool _busy = false;
  String? _last;
  int _hits = 0;

  @override
  void initState() {
    super.initState();
    // primo avvio: serve l'indirizzo del servizio
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if ((await AppSettings.serverUrl()).isEmpty && mounted) {
        await Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen()));
      }
    });
  }

  Future<void> _open(String code) async {
    if (_busy) return;
    _busy = true;
    await _scanner.stop();
    if (!mounted) return;
    await Navigator.push(context, MaterialPageRoute(
      builder: (_) => ResultScreen(barcode: code, radiusKm: _radiusKm),
    ));
    _busy = false;
    _last = null;
    _hits = 0;
    if (mounted) await _scanner.start();
  }

  /// Accetta solo codici con cifra di controllo valida, letti 2 volte di fila.
  void _onDetect(BarcodeCapture cap) {
    final raw = cap.barcodes.firstOrNull?.rawValue;
    if (raw == null) return;
    final code = normalizeGtin(raw);
    if (code == null) return; // lettura disturbata: ignorata
    if (code == _last) {
      if (++_hits >= 2) _open(code);
    } else {
      _last = code;
      _hits = 1;
    }
  }

  void _openManual() {
    final code = normalizeGtin(_manual.text);
    if (code == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Codice non valido: controlla le cifre (8, 12 o 13).')));
      return;
    }
    _open(code);
  }

  @override
  void dispose() {
    _scanner.dispose();
    _manual.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Prezzi Vicini'), actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: 'Impostazioni',
            onPressed: () => Navigator.push(
                context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ]),
        body: Column(children: [
          Expanded(
            child: ClipRRect(
              borderRadius: const BorderRadius.vertical(bottom: Radius.circular(24)),
              child: MobileScanner(
                controller: _scanner,
                onDetect: _onDetect,
                errorBuilder: (c, e, [_]) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text('Fotocamera non disponibile. Inserisci il codice a mano qui sotto.\n($e)',
                        textAlign: TextAlign.center),
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Column(children: [
              Row(children: [
                const Icon(Icons.place_outlined),
                const SizedBox(width: 8),
                Text('Raggio di ricerca: ${_radiusKm.round()} km'),
              ]),
              Slider(
                value: _radiusKm, min: 2, max: 30, divisions: 28,
                label: '${_radiusKm.round()} km',
                onChanged: (v) => setState(() => _radiusKm = v),
              ),
              TextField(
                controller: _manual,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: 'Oppure scrivi il codice a barre',
                  border: const OutlineInputBorder(),
                  suffixIcon: IconButton(icon: const Icon(Icons.search), onPressed: _openManual),
                ),
              ),
            ]),
          ),
          const SafeArea(top: false, child: SizedBox(height: 4)),
        ]),
      );
}
