"""Novità della versione 2: codici/prezzi nelle schede, sitemap, campione, OSM, classificazione blocchi."""
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from bs4 import BeautifulSoup
from probe import probe as pr
from probe.probe import Fetcher, Robots, candidate_links, is_product_url, probe_sitemap, render_summary
from probe.sample import is_italian_prefix, make_sample
from pvcore.page_check import find_gtins, find_prices

G = "8008490000021"


# ---------------------------------------------------------------- find_gtins / find_prices
def test_find_gtins_requires_a_key_and_a_valid_checksum():
    assert find_gtins('<script type="application/ld+json">{"@type":"Product","gtin13":"%s"}</script>' % G) == {G: "structured"}
    assert find_gtins('<script>var s={"ean":"%s"}</script>' % G) == {G: "json"}
    assert find_gtins("<p>Codice EAN: %s</p>" % G) == {G: "text"}
    assert find_gtins("<p>Rif. %s</p>" % G) == {}                   # numero senza chiave
    assert find_gtins("<p>EAN 8008490000022</p>") == {}             # cifra di controllo errata
    assert find_gtins("") == {} and find_gtins(None) == {}


def test_find_prices():
    html = ('<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer",'
            '"price":"1,29","priceCurrency":"EUR"}}</script>')
    assert find_prices(html) == [(1.29, "EUR")]
    assert find_prices('<meta property="product:price:amount" content="0.89">') == [(0.89, "?")]
    assert find_prices('<span itemprop="price" content="2.50"></span>') == [(2.5, "?")]
    assert find_prices("<p>Prezzo 1,29 €</p>") == []              # solo dati strutturati
    assert find_prices('<meta property="og:price:amount" content="0">') == []


# ---------------------------------------------------------------- candidati
def test_only_real_product_urls_are_candidates():
    assert is_product_url("https://x.it/prodotto/acqua-uliveto-15l")
    assert not is_product_url("https://x.it/ricerca?search=uliveto")
    assert not is_product_url("https://x.it/carte-e-premi/collezioni-e-concorsi")
    assert not is_product_url("https://x.it/it/punti-vendita/")
    assert not is_product_url("https://x.it/cioccolato-e-spalmabili_186")


def test_candidate_links_rejects_pages_that_are_not_products():
    html = ('<a href="/ricerca?search=Uliveto">Uliveto</a><a href="/chi-siamo">Uliveto chi siamo</a>'
            '<a href="/carte-e-premi/collezioni">Uliveto collezioni</a>'
            '<a href="/prodotto/acqua-uliveto-15l">Acqua Uliveto 1,5 L</a>')
    links, n = candidate_links(BeautifulSoup(html, "html.parser"), "https://x.it/", ["ulivet"])
    assert links == ["https://x.it/prodotto/acqua-uliveto-15l"] and n == 1


# ---------------------------------------------------------------- server finto con sitemap
def serve2(router):
    holder = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            status, body, ctype = router(u.path, parse_qs(u.query), holder["base"])
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    holder["base"] = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, holder["base"]


def product_html(i, gtin=True, price=True):
    node = {"@type": "Product", "name": f"Prodotto {i}"}
    if gtin:
        node["gtin13"] = G
    if price:
        node["offers"] = {"@type": "Offer", "price": "1.29", "priceCurrency": "EUR"}
    return ('<html><head><script type="application/ld+json">' + json.dumps(node) +
            f'</script></head><body><h1>Prodotto {i}</h1></body></html>')


def catalog(gtin=True, price=True, gz=True, index=True, robots_extra=""):
    def router(path, q, base):
        if path == "/robots.txt":
            return 200, f"User-agent: *\nDisallow: /admin\n{robots_extra}Sitemap: {base}sitemap.xml\n", "text/plain"
        if path == "/sitemap.xml":
            if index:
                return 200, (f"<sitemapindex><sitemap><loc>{base}sitemap-categorie.xml</loc></sitemap>"
                             f"<sitemap><loc>{base}sitemap-prodotti.xml{'.gz' if gz else ''}</loc></sitemap></sitemapindex>"), "application/xml"
            return 200, urlset(base), "application/xml"
        if path.startswith("/sitemap-prodotti"):
            body = urlset(base)
            return 200, (gzip.compress(body.encode()) if gz else body), ("application/x-gzip" if gz else "application/xml")
        if path == "/sitemap-categorie.xml":
            return 200, "<urlset><url><loc>%scategoria/a</loc></url></urlset>" % base, "application/xml"
        if path.startswith("/prodotto/item-"):
            return 200, product_html(path.rsplit("-", 1)[1], gtin, price), "text/html"
        return 404, "no", "text/plain"

    def urlset(base):
        return "<urlset>" + "".join(f"<url><loc>{base}prodotto/item-{i}</loc></url>" for i in range(30)) + "</urlset>"
    return router


@pytest.fixture
def sm():
    servers = []

    def _run(router):
        srv, base = serve2(router)
        servers.append(srv)
        f = Fetcher(min_interval=0, timeout=3)
        return probe_sitemap(base.rstrip("/"), f, Robots(f))

    yield _run
    for s in servers:
        s.shutdown()


def test_sitemap_gz_index_codice_e_prezzo(sm):
    r = sm(catalog())
    assert r["esito"] == "codice_e_prezzo"
    assert r["pagine_lette"] == 3 and r["pagine_con_gtin"] == 3 and r["pagine_con_codice_e_prezzo"] == 3
    assert r["sotto_sitemap"].endswith("sitemap-prodotti.xml.gz")        # non ha scelto le categorie
    assert next(iter(r["pagine"][0]["gtin"])) == G


def test_sitemap_plain_urlset(sm):
    assert sm(catalog(gz=False, index=False))["esito"] == "codice_e_prezzo"


def test_sitemap_only_code_only_price_neither(sm):
    assert sm(catalog(price=False))["esito"] == "solo_codice"
    assert sm(catalog(gtin=False))["esito"] == "solo_prezzo"
    assert sm(catalog(gtin=False, price=False))["esito"] == "ne_codice_ne_prezzo"


def test_sitemap_missing(sm):
    def router(path, q, base):
        return (200, "User-agent: *\nDisallow:", "text/plain") if path == "/robots.txt" else (404, "no", "text/plain")
    assert sm(router)["esito"] == "sitemap_non_leggibile"


def test_sitemap_respects_robots_for_product_pages(sm):
    r = sm(catalog(robots_extra="Disallow: /prodotto/\n"))
    assert r["esito"] == "schede_bloccate"
    assert all(p["esito"] == "robots_vieta" for p in r["pagine"])


def test_sitemap_result_is_shared_between_chains_on_one_platform():
    srv, base = serve2(catalog())
    try:
        f = Fetcher(min_interval=0, timeout=3)
        rb = Robots(f)
        a = probe_sitemap(base.rstrip("/"), f, rb)
        n = f.requests_made
        b = probe_sitemap(base.rstrip("/"), f, rb)
        assert b.get("condiviso") and f.requests_made == n and a["esito"] == b["esito"]
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- classificazione blocchi
@pytest.mark.parametrize("status", [403, 202, 429, 503])
def test_waf_on_robots_is_not_a_prohibition(status):
    def router(path, q, base):
        return (status, "x", "text/plain")
    srv, base = serve2(router)
    try:
        f = Fetcher(min_interval=0, timeout=3)
        r = pr.probe_site({"name": "w", "base": base}, [{"gtin": G, "brand": "Uliveto", "name": "x"}], f, Robots(f))
        assert r["esito"] == "bloccato_waf_o_robots_illeggibile"
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- campione automatico
def test_italian_prefix():
    assert is_italian_prefix("8008490000021") and is_italian_prefix("8398765432104"[:13])
    assert not is_italian_prefix("3274080005003") and not is_italian_prefix("5449000054227")
    assert not is_italian_prefix("42104964")


def test_make_sample_filters_and_paginates():
    pages = {
        "1": [{"code": "3274080005003", "product_name": "Cristaline", "brands": "Cristaline", "quantity": "1500 ml"},   # francese
              {"code": "8008490000021", "product_name": "Acqua", "brands": "Uliveto", "quantity": "1,5 L"},
              {"code": "8008490000022", "product_name": "Errato", "brands": "X", "quantity": "1 L"},                    # checksum
              {"code": "8076800195057", "product_name": "Spaghetti", "brands": "Barilla", "quantity": ""}],             # no formato
        "2": [{"code": "8076809523547", "product_name_it": "Pesto Rosso", "brands": "Barilla", "quantity": "200 g"},
              {"code": "8076800105056", "product_name": "Penne", "brands": "Barilla", "quantity": "500 g"},
              {"code": "8076800376008", "product_name": "Fusilli", "brands": "Barilla", "quantity": "500 g"}],          # 3ª Barilla
    }

    def router(path, q, base):
        return 200, json.dumps({"products": pages.get(q.get("page", ["1"])[0], [])}), "application/json"
    srv, base = serve2(router)
    try:
        chosen, log = make_sample(Fetcher(min_interval=0, timeout=3), n=12, pages=4, base=base.rstrip("/"))
    finally:
        srv.shutdown()
    brands = [c["brand"] for c in chosen]
    assert "Cristaline" not in brands and brands.count("Barilla") <= 2 and "Uliveto" in brands
    assert all(is_italian_prefix(c["gtin"]) for c in chosen)
    assert len(log) >= 2


def test_make_sample_survives_server_errors():
    srv, base = serve2(lambda p, q, b: (503, "giù", "text/plain"))
    try:
        chosen, log = make_sample(Fetcher(min_interval=0, timeout=3), base=base.rstrip("/"))
    finally:
        srv.shutdown()
    assert chosen == [] and "HTTP 503" in log[0]


# ---------------------------------------------------------------- OpenStreetMap
class FakeResp:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


def test_osm_retries_other_servers(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        if "overpass-api" in url:
            return FakeResp(502)
        return FakeResp(200, {"elements": [{"tags": {"shop": "supermarket", "brand": "Conad", "brand:wikidata": "Q1"}},
                                           {"tags": {"shop": "supermarket", "name": "Da Mario"}}]})
    monkeypatch.setattr(pr.requests, "post", fake_post)
    out = pr.probe_osm({"Roma": (41.9, 12.5)}, pause=0, retry_pause=0)
    assert out["Roma"]["supermercati"] == 2 and out["Roma"]["con_brand_wikidata"] == 1 and out["Roma"]["solo_nome"] == 1
    assert "kumi" in out["Roma"]["server"] and len(calls) == 2


def test_osm_reports_all_failures(monkeypatch):
    monkeypatch.setattr(pr.requests, "post", lambda url, **kw: FakeResp(502))
    out = pr.probe_osm({"Roma": (41.9, 12.5)}, pause=0, retry_pause=0)
    assert "errore" in out["Roma"] and "502" in out["Roma"]["errore"]


# ---------------------------------------------------------------- riepilogo
def test_summary_has_decisive_section():
    res = {"generato": "x", "richieste": 1, "siti": [
        {"nome": "Catena A", "esito": "nessun_form_ricerca", "sitemap_probe": {
            "esito": "codice_e_prezzo", "pagine_lette": 3, "pagine_con_gtin": 3, "pagine_con_prezzo": 3,
            "pagine": [{"gtin": {G: "structured"}, "prezzi": [(1.29, "EUR")], "titolo": "Acqua"}]}},
        {"nome": "Catena B", "esito": "bloccato_waf_o_robots_illeggibile"}]}
    md = render_summary(res)
    assert "misura decisiva" in md and "codice_e_prezzo" in md and G in md and "1.29" in md
    assert "sitemap_non_provata" in md
