/// Valida un codice a barre (EAN-8, UPC-A, EAN-13, GTIN-14) con la cifra di
/// controllo e lo porta al formato a 13 cifre. Ritorna null se non è valido:
/// è il filtro che scarta le letture disturbate della fotocamera.
String? normalizeGtin(String raw) {
  final d = raw.replaceAll(RegExp(r'\D'), '');
  if (![8, 12, 13, 14].contains(d.length)) return null;
  var sum = 0;
  for (var i = 0; i < d.length - 1; i++) {
    sum += int.parse(d[d.length - 2 - i]) * (i.isEven ? 3 : 1);
  }
  if ((10 - sum % 10) % 10 != int.parse(d[d.length - 1])) return null;
  if (d.length == 12) return '0$d';
  if (d.length == 14 && d.startsWith('0')) return d.substring(1);
  return d;
}
