// Cosa mostrare e con quali parole. Dart puro, quindi verificabile senza telefono.
import 'models.dart';

enum Tone { certain, probable, none, info }

class RowVm {
  final String title;
  final String? subtitle, trailing, badge, url;
  final Tone tone;
  const RowVm(this.title, {this.subtitle, this.trailing, this.badge, this.url, this.tone = Tone.certain});
}

class SectionVm {
  final String id, title;
  final String? note, emptyText;
  final Tone tone;
  final bool collapsed;
  final List<RowVm> rows;
  const SectionVm(this.id, this.title, this.rows,
      {this.note, this.emptyText, this.tone = Tone.certain, this.collapsed = false});
}

class ResultVm {
  final String headline;
  final String? subline, imageUrl;
  final bool recognized, canSuggestName;
  final List<SectionVm> sections;
  final List<LimitItem> limits; // avvisi prima, informazioni dopo
  const ResultVm(this.headline, this.subline, this.imageUrl, this.recognized, this.canSuggestName, this.sections, this.limits);
}

String formatDistance(int m) {
  if (m < 1000) return '$m m';
  final km = (m / 100).round() / 10;
  return '${km.toStringAsFixed(1).replaceAll('.', ',')} km';
}

String formatPrice(double p, [String? currency]) {
  final s = p.toStringAsFixed(2).replaceAll('.', ',');
  return (currency == null || currency == 'EUR') ? '$s €' : '$s $currency';
}

String formatDate(String? iso) {
  if (iso == null || iso.length < 10) return '';
  final p = iso.substring(0, 10).split('-');
  return p.length == 3 ? '${p[2]}/${p[1]}/${p[0]}' : '';
}

Tone _toneForLevel(int level) => level <= 2 ? Tone.certain : Tone.probable;

ResultVm buildResult(ScanResponse r) {
  final p = r.product;
  String headline;
  String? subline;
  switch (p.state) {
    case 'riconosciuto':
      headline = [p.brand, p.name].where((e) => e != null && e.isNotEmpty).join(' — ');
      if (headline.isEmpty) headline = 'Prodotto ${r.gtin}';
      subline = [if (p.quantity != null) p.quantity!, r.gtin, if (p.source != null) 'fonte: ${p.source}'].join(' · ');
      break;
    case 'errore_fonte':
      headline = 'Prodotto non verificabile ora';
      subline = r.gtin;
      break;
    default:
      headline = 'Prodotto non riconosciuto';
      subline = p.nameHint == null
          ? r.gtin
          : '${r.gtin} · ${p.nameHintSource ?? 'suggerimento'}: «${p.nameHint}»';
  }

  String offersEmpty;
  switch (r.offersState.state) {
    case 'non_configurato':
      offersEmpty = 'Prezzi online non attivi: manca la chiave del servizio di ricerca.';
      break;
    case 'quota_esaurita':
      offersEmpty = 'Quota gratuita mensile di ricerche esaurita: nessun prezzo salvato per questo prodotto.';
      break;
    case 'errore':
      offersEmpty = 'Ricerca dei prezzi non riuscita${r.offersState.error == null ? '' : ': ${r.offersState.error}'}.';
      break;
    default:
      offersEmpty = 'Nessun prezzo online trovato per questo prodotto.';
  }
  final offers = SectionVm(
    'offers',
    'Prezzi online (riferimento)',
    [
      for (final o in r.onlineOffers)
        RowVm(
          o.store,
          subtitle: o.title,
          trailing: formatPrice(o.price, o.currency),
          badge: o.byName
              ? 'somiglianza di nome: controlla che sia lo stesso prodotto'
              : 'trovato cercando il codice a barre',
          url: o.url,
          tone: o.byName ? Tone.probable : Tone.info,
        ),
    ],
    emptyText: offersEmpty,
    note: r.onlineOffers.isEmpty
        ? null
        : 'Riferimenti da ${r.onlineOffers.first.source}: spedizione e disponibilità dipendono dal negozio online.',
    tone: Tone.info,
  );

  final nameMatches = SectionVm(
    'namematches',
    'Possibili corrispondenze nei cataloghi (per nome)',
    [
      for (final c in r.catalogNameMatches)
        RowVm(
          c.chain,
          subtitle: c.title,
          trailing: c.price == null ? null : formatPrice(c.price!, c.currency),
          badge: c.levelLabel,
          url: c.url,
          tone: Tone.probable,
        ),
    ],
    note: 'Non verificate col codice a barre: controlla che sia lo stesso prodotto.',
    tone: Tone.probable,
  );

  final catalogs = SectionVm(
    'catalogs',
    'Cataloghi online che hanno il prodotto',
    [
      for (final c in r.catalogs)
        RowVm(
          c.chain,
          subtitle: [c.levelLabel, if (c.verifiedAt != null) 'verificato il ${formatDate(c.verifiedAt)}'].join(' · '),
          trailing: c.price == null ? 'prezzo non indicato' : formatPrice(c.price!, c.currency),
          badge: c.price == null ? null : 'prezzo del sito online',
          url: c.url,
          tone: _toneForLevel(c.level),
        ),
    ],
    emptyText: 'Nessun catalogo online ha confermato questo prodotto con il codice a barre.',
    note: r.catalogs.isEmpty
        ? null
        : 'Il prezzo è quello del sito online: nel negozio fisico può essere diverso.',
  );

  final withProduct = SectionVm(
    'stores',
    'Negozi vicini di catene che hanno il prodotto',
    [
      for (final s in r.storesWithProduct)
        RowVm(
          s.name ?? s.chain ?? 'Negozio',
          subtitle: [formatDistance(s.distanceM), if (s.address != null) s.address!].join(' · '),
          badge: s.basis?.label,
          url: s.basis?.url,
          tone: _toneForLevel(s.basis?.level ?? 5),
        ),
    ],
    emptyText: !r.positionUsed
        ? 'Posizione non indicata: non possiamo mostrare i negozi vicini.'
        : 'Nessun negozio vicino appartiene a una catena con una prova per questo prodotto.',
    note: r.storesWithProduct.isEmpty
        ? null
        : 'Il catalogo contiene il prodotto, ma non sappiamo se questo negozio lo abbia in magazzino né a che prezzo.',
  );

  final others = SectionVm(
    'others',
    'Altri negozi vicini: nessuna informazione sul prodotto',
    [
      for (final s in r.storesWithoutInfo)
        RowVm(s.name ?? s.chain ?? 'Negozio',
            subtitle: [formatDistance(s.distanceM), if (s.address != null) s.address!].join(' · '), tone: Tone.none),
    ],
    emptyText: r.positionUsed ? 'Nessun altro negozio nei dati di questa zona.' : null,
    tone: Tone.none,
    collapsed: true,
    note: 'Non sappiamo se vendono questo prodotto.',
  );

  final limits = [...r.limits.where((l) => l.isWarning), ...r.limits.where((l) => !l.isWarning)];
  return ResultVm(headline, subline, p.imageUrl, p.recognized, p.state == 'non_riconosciuto',
      [offers, catalogs, if (r.catalogNameMatches.isNotEmpty) nameMatches, withProduct, others], limits);
}
