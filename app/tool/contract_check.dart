// Verifica che l'app legga gli esempi di risposta generati dal server vero.
// Uso:  dart run tool/contract_check.dart ../tests/fixtures/api
import 'dart:convert';
import 'dart:io';

import '../lib/gtin.dart';
import '../lib/models.dart';
import '../lib/view_model.dart';

int failures = 0;
void check(bool ok, String what) {
  if (!ok) {
    failures++;
    stderr.writeln('FALLITO: $what');
  }
}

ScanResponse load(String dir, String name) =>
    ScanResponse.fromJson(jsonDecode(File('$dir/$name.json').readAsStringSync()) as Map<String, dynamic>);

void main(List<String> args) {
  final dir = args.isEmpty ? '../tests/fixtures/api' : args.first;

  // --- formattazione
  check(formatDistance(350) == '350 m', 'distanza breve');
  check(formatDistance(1234) == '1,2 km', 'distanza lunga');
  check(formatDistance(999) == '999 m', '999 m');
  check(formatPrice(0.89, 'EUR') == '0,89 €', 'prezzo');
  check(formatDate('2026-11-24T12:29:04Z') == '24/11/2026', 'data');
  check(normalizeGtin('8008490000021') == '8008490000021', 'gtin valido');
  check(normalizeGtin('8008490000022') == null, 'gtin con cifra errata');
  check(normalizeGtin('036000291452') == '0036000291452', 'upc-a');

  // --- risposta completa
  final full = load(dir, 'scan_full');
  check(full.product.recognized && full.product.brand == 'Uliveto', 'prodotto riconosciuto');
  check(full.catalogs.length == 1 && full.catalogs.first.level == 1 && full.catalogs.first.price == 0.89, 'catalogo');
  check(full.storesWithProduct.map((s) => s.name).toList().join(',') == 'Conad City,Conad Superstore', 'negozi con prova');
  check(full.storesWithProduct.first.basis != null && full.storesWithProduct.first.basis!.level == 1, 'basi');
  check(full.storesWithProduct.first.distanceM == 300 && full.storesWithProduct.last.distanceM > 800, 'distanze dei negozi');
  check(full.storesWithProduct.first.address == 'Via Prova 1' && full.storesWithProduct.first.lat != null, 'indirizzo e coordinate');
  check(full.catalogs.first.url.startsWith('http') && full.catalogs.first.verifiedAt != null && full.catalogs.first.title != null, 'dati del catalogo');
  check(full.catalogs.first.levelLabel.startsWith('Verificato') && full.storesWithProduct.first.basis!.label.startsWith('Verificato'), 'etichette di fiducia');
  check(full.radiusKm == 10.0 && full.positionUsed && full.indexing.chainsConfirmed == 1 && full.indexing.state == 'completata', 'indicizzazione');
  check(full.storesWithoutInfo.first.distanceM == 200, 'distanza negozi senza info');
  check(full.storesWithoutInfo.isNotEmpty && full.storesWithoutInfo.every((s) => s.basis == null), 'negozi senza info');
  check(full.limits.any((l) => l.code == 'PRICE_STORE'), 'limite prezzo');
  final vm = buildResult(full);
  check(vm.headline == 'Uliveto — Acqua Minerale Naturale', 'titolo: ${vm.headline}');
  check(vm.sections[0].rows.length == 1 && vm.sections[0].rows.first.trailing == '0,89 €', 'riga catalogo');
  check(vm.sections[0].rows.first.badge == 'prezzo del sito online', 'il prezzo dice di essere online');
  check(vm.sections[1].rows.length == 2 && vm.sections[2].collapsed, 'sezioni');
  check(vm.sections[1].rows.first.subtitle == '300 m · Via Prova 1', 'riga negozio: ${vm.sections[1].rows.first.subtitle}');
  check(vm.limits.first.isWarning || vm.limits.every((l) => !l.isWarning), 'avvisi prima delle informazioni');

  // --- prodotto sconosciuto: deve dirlo chiaramente
  final unk = load(dir, 'scan_unknown');
  final u = buildResult(unk);
  check(!u.recognized && u.canSuggestName && u.headline == 'Prodotto non riconosciuto', 'non riconosciuto');
  check(u.sections[0].rows.isEmpty && u.sections[0].emptyText!.contains('Nessun catalogo'), 'nessun catalogo: testo');
  check(u.limits.first.isWarning && u.limits.any((l) => l.code == 'PRODUCT_NOT_RECOGNIZED'), 'limite non riconosciuto');

  // --- marchio proprio: probabile, non certo
  final own = buildResult(load(dir, 'scan_own_brand'));
  check(own.sections[1].rows.length == 1 && own.sections[1].rows.first.tone == Tone.probable, 'marchio proprio = probabile');
  check(own.sections[1].rows.first.badge!.startsWith('Probabile'), 'etichetta probabile');
  check(own.sections[0].rows.isEmpty, 'nessun catalogo per marchio proprio');

  // --- senza posizione e senza cataloghi
  final np = buildResult(load(dir, 'scan_no_position'));
  check(np.sections[1].rows.isEmpty && np.sections[1].emptyText!.contains('Posizione non indicata'), 'senza posizione');
  final nc = load(dir, 'scan_no_catalogs');
  check(nc.indexing.state == 'non_disponibile' && nc.limits.any((l) => l.code == 'NO_CATALOGS_QUERYABLE'), 'nessun catalogo consultabile');

  // --- versione non compatibile
  var rejected = false;
  try {
    ScanResponse.fromJson({'schema': 99});
  } on FormatException {
    rejected = true;
  }
  check(rejected, 'schema sconosciuto rifiutato');

  // --- campi mancanti non fanno crollare l'app
  final minimal = ScanResponse.fromJson({'schema': 1});
  check(minimal.catalogs.isEmpty && minimal.product.state == 'non_riconosciuto', 'risposta minima');

  if (failures == 0) {
    stdout.writeln('OK: tutti i controlli superati');
  } else {
    stderr.writeln('$failures controlli falliti');
    exit(1);
  }
}
