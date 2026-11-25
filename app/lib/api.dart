// Client del servizio. Dart puro (dart:io): una sola chiamata per scansione.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'models.dart';

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

class PvApi {
  final String baseUrl;
  final Duration timeout;
  // Il servizio gratuito si addormenta dopo un po' di inattività: il risveglio può richiedere circa un minuto.
  PvApi(this.baseUrl, {this.timeout = const Duration(seconds: 100)});

  Uri _uri(String path, [Map<String, String>? query]) {
    final b = Uri.parse(baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl);
    return b.replace(path: '${b.path}$path', queryParameters: query);
  }

  Future<Map<String, dynamic>> _json(String method, Uri uri, {Object? body}) async {
    final c = HttpClient()..connectionTimeout = const Duration(seconds: 10);
    try {
      final req = await (method == 'GET' ? c.getUrl(uri) : c.postUrl(uri)).timeout(timeout);
      req.headers.set('Accept', 'application/json');
      if (body != null) {
        req.headers.contentType = ContentType.json;
        req.add(utf8.encode(jsonEncode(body)));
      }
      final res = await req.close().timeout(timeout);
      final text = await res.transform(utf8.decoder).join().timeout(timeout);
      if (res.statusCode != 200) {
        var detail = '';
        try {
          final j = jsonDecode(text);
          if (j is Map && j['detail'] != null) detail = ': ${j['detail']}';
        } catch (_) {}
        throw ApiException('Il servizio ha risposto ${res.statusCode}$detail');
      }
      final j = jsonDecode(text);
      if (j is! Map<String, dynamic>) throw ApiException('Risposta del servizio non valida.');
      return j;
    } on ApiException {
      rethrow;
    } on SocketException {
      throw ApiException('Servizio non raggiungibile: controlla l\'indirizzo del server e la connessione.');
    } on TimeoutException {
      throw ApiException('Il servizio non risponde (tempo scaduto).');
    } on HandshakeException {
      throw ApiException('Connessione sicura non riuscita: controlla l\'indirizzo del server (https).');
    } on FormatException {
      throw ApiException('Risposta del servizio non valida.');
    } finally {
      c.close(force: true);
    }
  }

  Future<ScanResponse> scan(String code, {double? lat, double? lon, double? radiusKm}) async {
    final q = <String, String>{
      'code': code,
      if (lat != null && lon != null) ...{'lat': '$lat', 'lon': '$lon'},
      if (radiusKm != null) 'radius_km': '$radiusKm',
    };
    final j = await _json('GET', _uri('/v1/scan', q));
    try {
      return ScanResponse.fromJson(j);
    } on FormatException catch (e) {
      throw ApiException(e.message);
    }
  }

  /// Propone una correzione (nome, marca o formato). Si applica solo quando 3 utenti diversi concordano.
  Future<String> sendCorrection(String code, String field, String value, String userId) async {
    final j = await _json('POST', _uri('/v1/corrections'),
        body: {'code': code, 'field': field, 'value': value, 'user_id': userId});
    return (j['note'] ?? 'Correzione registrata.').toString();
  }
}
