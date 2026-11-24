// Modelli della risposta del servizio (/v1/scan). Dart puro: nessuna dipendenza da Flutter.

String? _str(dynamic v) => v == null ? null : v.toString();
double? _dbl(dynamic v) => v is num ? v.toDouble() : null;
int _int(dynamic v, [int d = 0]) => v is num ? v.toInt() : d;
List<T> _list<T>(dynamic v, T Function(Map<String, dynamic>) f) =>
    v is List ? [for (final e in v) if (e is Map<String, dynamic>) f(e)] : <T>[];

class ProductInfo {
  final String state; // riconosciuto | non_riconosciuto | errore_fonte
  final String? name, brand, quantity, imageUrl, source, ownBrandChain;
  final List<String> correctedFields;
  const ProductInfo({
    required this.state,
    this.name,
    this.brand,
    this.quantity,
    this.imageUrl,
    this.source,
    this.ownBrandChain,
    this.correctedFields = const [],
  });
  bool get recognized => state == 'riconosciuto';
  factory ProductInfo.fromJson(Map<String, dynamic> j) => ProductInfo(
        state: _str(j['state']) ?? 'non_riconosciuto',
        name: _str(j['name']),
        brand: _str(j['brand']),
        quantity: _str(j['quantity']),
        imageUrl: _str(j['image_url']),
        source: _str(j['source']),
        ownBrandChain: _str(j['own_brand_chain']),
        correctedFields: [for (final e in (j['corrected_fields'] as List? ?? [])) e.toString()],
      );
}

class CatalogItem {
  final String chain, levelLabel, url;
  final int level;
  final String? title, currency, verifiedAt;
  final double? price;
  const CatalogItem({
    required this.chain,
    required this.level,
    required this.levelLabel,
    required this.url,
    this.title,
    this.price,
    this.currency,
    this.verifiedAt,
  });
  factory CatalogItem.fromJson(Map<String, dynamic> j) => CatalogItem(
        chain: _str(j['chain']) ?? '',
        level: _int(j['level']),
        levelLabel: _str(j['level_label']) ?? '',
        url: _str(j['url']) ?? '',
        title: _str(j['title']),
        price: _dbl(j['price']),
        currency: _str(j['currency']),
        verifiedAt: _str(j['verified_at']),
      );
}

class Basis {
  final int level;
  final String label;
  final String? url, currency;
  final double? price;
  const Basis({required this.level, required this.label, this.url, this.price, this.currency});
  factory Basis.fromJson(Map<String, dynamic> j) => Basis(
        level: _int(j['level']),
        label: _str(j['label']) ?? '',
        url: _str(j['url']),
        price: _dbl(j['price']),
        currency: _str(j['currency']),
      );
}

class StoreItem {
  final String? chain, name, address, openingHours;
  final int distanceM;
  final double? lat, lon;
  final Basis? basis; // assente per i negozi "senza informazioni"
  const StoreItem({
    this.chain,
    this.name,
    required this.distanceM,
    this.address,
    this.openingHours,
    this.lat,
    this.lon,
    this.basis,
  });
  factory StoreItem.fromJson(Map<String, dynamic> j) => StoreItem(
        chain: _str(j['chain']),
        name: _str(j['name']),
        distanceM: _int(j['distance_m']),
        address: _str(j['address']),
        openingHours: _str(j['opening_hours']),
        lat: _dbl(j['lat']),
        lon: _dbl(j['lon']),
        basis: j['basis'] is Map<String, dynamic> ? Basis.fromJson(j['basis'] as Map<String, dynamic>) : null,
      );
}

class IndexingInfo {
  final String state; // completata | parziale | non_disponibile
  final int chainsConsultable, chainsTried, chainsConfirmed;
  const IndexingInfo({
    required this.state,
    required this.chainsConsultable,
    required this.chainsTried,
    required this.chainsConfirmed,
  });
  factory IndexingInfo.fromJson(Map<String, dynamic> j) => IndexingInfo(
        state: _str(j['state']) ?? 'non_disponibile',
        chainsConsultable: _int(j['chains_consultable']),
        chainsTried: _int(j['chains_tried']),
        chainsConfirmed: _int(j['chains_confirmed']),
      );
}

class LimitItem {
  final String code, severity, text; // severity: info | warning
  const LimitItem({required this.code, required this.severity, required this.text});
  bool get isWarning => severity == 'warning';
  factory LimitItem.fromJson(Map<String, dynamic> j) =>
      LimitItem(code: _str(j['code']) ?? '', severity: _str(j['severity']) ?? 'info', text: _str(j['text']) ?? '');
}

class ScanResponse {
  static const supportedSchema = 1;
  final String gtin;
  final double radiusKm;
  final bool positionUsed;
  final ProductInfo product;
  final List<CatalogItem> catalogs;
  final List<StoreItem> storesWithProduct, storesWithoutInfo;
  final IndexingInfo indexing;
  final List<LimitItem> limits;
  const ScanResponse({
    required this.gtin,
    required this.radiusKm,
    required this.positionUsed,
    required this.product,
    required this.catalogs,
    required this.storesWithProduct,
    required this.storesWithoutInfo,
    required this.indexing,
    required this.limits,
  });
  factory ScanResponse.fromJson(Map<String, dynamic> j) {
    if (_int(j['schema']) != supportedSchema) {
      throw const FormatException('Versione del servizio non compatibile: aggiorna l\'app.');
    }
    return ScanResponse(
      gtin: _str(j['gtin']) ?? '',
      radiusKm: _dbl(j['radius_km']) ?? 0,
      positionUsed: j['position_used'] == true,
      product: ProductInfo.fromJson((j['product'] as Map<String, dynamic>?) ?? const {}),
      catalogs: _list(j['catalogs'], CatalogItem.fromJson),
      storesWithProduct: _list(j['stores_with_product_in_catalog'], StoreItem.fromJson),
      storesWithoutInfo: _list(j['stores_without_information'], StoreItem.fromJson),
      indexing: IndexingInfo.fromJson((j['indexing'] as Map<String, dynamic>?) ?? const {}),
      limits: _list(j['limits'], LimitItem.fromJson),
    );
  }
}
