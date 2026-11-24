import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../settings.dart';
import '../view_model.dart';
import 'settings_screen.dart';

class ResultScreen extends StatefulWidget {
  final String barcode;
  final double radiusKm;
  const ResultScreen({super.key, required this.barcode, required this.radiusKm});
  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  ResultVm? _vm;
  String? _error;
  String? _locationNote;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<Position?> _position() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      _locationNote = 'Posizione disattivata: i negozi vicini non sono disponibili.';
      return null;
    }
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
    if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
      _locationNote = 'Permesso di posizione negato: i negozi vicini non sono disponibili.';
      return null;
    }
    return Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium));
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _locationNote = null;
    });
    try {
      final server = await AppSettings.serverUrl();
      if (server.isEmpty) throw ApiException('Indirizzo del servizio non impostato.');
      final pos = await _position();
      // La posizione viene arrotondata (circa 1 km): al servizio basta questo.
      final r = await PvApi(server).scan(
        widget.barcode,
        lat: pos == null ? null : double.parse(pos.latitude.toStringAsFixed(2)),
        lon: pos == null ? null : double.parse(pos.longitude.toStringAsFixed(2)),
        radiusKm: widget.radiusKm,
      );
      if (mounted) setState(() {
            _vm = buildResult(r);
            _loading = false;
          });
    } on ApiException catch (e) {
      if (mounted) setState(() {
            _error = e.message;
            _loading = false;
          });
    } catch (e) {
      if (mounted) setState(() {
            _error = 'Errore imprevisto: $e';
            _loading = false;
          });
    }
  }

  Future<void> _openUrl(String url) async {
    try {
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Impossibile aprire il link.')));
      }
    }
  }

  Future<void> _suggest() async {
    final name = TextEditingController();
    final brand = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Proponi nome e marca'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('La correzione vale per tutti solo quando 3 utenti diversi propongono lo stesso valore.'),
          const SizedBox(height: 8),
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Nome del prodotto')),
          TextField(controller: brand, decoration: const InputDecoration(labelText: 'Marca')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Invia')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final api = PvApi(await AppSettings.serverUrl());
      final user = await AppSettings.userId();
      String note = 'Nessun dato inserito.';
      if (name.text.trim().isNotEmpty) note = await api.sendCorrection(widget.barcode, 'name', name.text, user);
      if (brand.text.trim().isNotEmpty) note = await api.sendCorrection(widget.barcode, 'brand', brand.text, user);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(note)));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Color _color(Tone t) {
    switch (t) {
      case Tone.certain:
        return Colors.green.shade700;
      case Tone.probable:
        return Colors.orange.shade800;
      case Tone.none:
        return Colors.grey.shade600;
      case Tone.info:
        return Colors.blue.shade700;
    }
  }

  IconData _icon(Tone t) {
    switch (t) {
      case Tone.certain:
        return Icons.verified;
      case Tone.probable:
        return Icons.help_outline;
      case Tone.none:
        return Icons.remove_circle_outline;
      case Tone.info:
        return Icons.info_outline;
    }
  }

  Widget _row(RowVm r) => ListTile(
        leading: Icon(_icon(r.tone), color: _color(r.tone)),
        title: Text(r.title),
        subtitle: (r.subtitle == null && r.badge == null)
            ? null
            : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (r.subtitle != null) Text(r.subtitle!),
                if (r.badge != null)
                  Text(r.badge!, style: TextStyle(color: _color(r.tone), fontSize: 12)),
              ]),
        trailing: r.trailing == null
            ? (r.url == null ? null : const Icon(Icons.open_in_new, size: 18))
            : Text(r.trailing!, style: const TextStyle(fontWeight: FontWeight.bold)),
        onTap: r.url == null ? null : () => _openUrl(r.url!),
      );

  Widget _section(SectionVm s) {
    final body = s.rows.isEmpty
        ? [Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 12), child: Text(s.emptyText ?? '—'))]
        : [
            for (final r in s.rows) _row(r),
            if (s.note != null)
              Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
                  child: Text(s.note!, style: const TextStyle(fontSize: 12))),
          ];
    if (s.collapsed) {
      return Card(
        child: ExpansionTile(
          title: Text(s.title),
          subtitle: s.note == null ? null : Text(s.note!),
          children: body,
        ),
      );
    }
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
          child: Text(s.title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        ),
        ...body,
      ]),
    );
  }

  Widget _limits(List limits) => Card(
        color: Colors.amber.shade50,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Cosa non sappiamo', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            for (final l in limits)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(l.isWarning ? Icons.warning_amber : Icons.info_outline,
                      size: 18, color: l.isWarning ? Colors.orange.shade800 : Colors.blue.shade700),
                  const SizedBox(width: 8),
                  Expanded(child: Text(l.text)),
                ]),
              ),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Riprova')),
            TextButton(
              onPressed: () => Navigator.push(
                  context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
              child: const Text('Impostazioni'),
            ),
          ]),
        ),
      );
    } else {
      final vm = _vm!;
      body = ListView(padding: const EdgeInsets.all(12), children: [
        Card(
          child: ListTile(
            leading: vm.imageUrl == null
                ? const Icon(Icons.shopping_basket_outlined, size: 40)
                : Image.network(vm.imageUrl!, width: 48, height: 48,
                    errorBuilder: (c, e, s) => const Icon(Icons.shopping_basket_outlined, size: 40)),
            title: Text(vm.headline, style: const TextStyle(fontWeight: FontWeight.bold)),
            subtitle: vm.subline == null ? null : Text(vm.subline!),
            trailing: vm.canSuggestName
                ? IconButton(icon: const Icon(Icons.edit), tooltip: 'Proponi nome e marca', onPressed: _suggest)
                : null,
          ),
        ),
        if (_locationNote != null)
          Padding(padding: const EdgeInsets.all(8), child: Text(_locationNote!)),
        for (final s in vm.sections) _section(s),
        _limits(vm.limits),
      ]);
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Risultato'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _loading ? null : _load),
      ]),
      body: body,
    );
  }
}
