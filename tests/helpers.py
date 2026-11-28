import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

G = "8008490000021"


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


FORM = '<html><body><form action="/cerca" method="get"><input type="search" name="q"></form></body></html>'


def page_for(mode, gtin):
    node = {"@type": "Product", "name": "Acqua Uliveto 1,5 L", "offers": {"@type": "Offer", "price": "0.89", "priceCurrency": "EUR"}}
    if mode == "json":
        node["gtin13"] = gtin
        return '<script type="application/ld+json">%s</script><h1>Acqua Uliveto</h1>' % json.dumps(node)
    if mode == "text":
        return "<h1>Acqua Uliveto 1,5 L</h1><p>Codice EAN: %s</p>" % gtin
    if mode == "othercode":
        node["gtin13"] = "8020141800002"
        return '<script type="application/ld+json">%s</script><h1>Acqua Sant Anna</h1>' % json.dumps(node)
    if mode == "carousel":
        return ("<h1>Acqua</h1><p>EAN 8020141800002</p><ul><li>%s</li><li>8001620014172</li><li>80134091</li></ul>" % gtin)
    if mode == "nocode_variant":
        return "<h1>Acqua Uliveto Zero 1,5 L</h1><p>Prezzo 0,99 €</p>"
    return "<h1>Acqua Uliveto 1,5 L</h1><p>Prezzo 0,89 €</p>"          # nocode


def catalog_router(mode="json", gtin=G, hits=None, delay=0.0, robots="User-agent: *\nDisallow: /admin\n",
                   home=FORM, search_status=200, by_name=False, decoys=0, odd_link=False):
    hits = hits if hits is not None else []

    def router(path, q, base):
        hits.append(path)
        if path == "/robots.txt":
            return 200, robots, "text/plain"
        if path == "/":
            return 200, home, "text/html"
        if path == "/cerca":
            time.sleep(delay)
            if search_status != 200:
                return search_status, "Just a moment... cf-chl", "text/html"
            term = (q.get("q") or [""])[0]
            found = term == gtin or (by_name and term != gtin and "uliveto" in term.lower())
            if not found:
                body = "<p>Nessun risultato</p>"
            else:
                href = "/vai/xyz-777" if odd_link else "/prodotto/acqua-1"          # indirizzo senza percorso da "prodotto"
                card = f'<div class="card" data-ean="{gtin}"><a href="{href}">Acqua Uliveto</a></div>'
                esche = "".join(f'<div class="card"><a href="/prodotto/uliveto-esca-{i}">Uliveto Esca {i}</a></div>' for i in range(decoys))
                menu = '<nav><a href="/prodotto/promo-menu">Offerte Uliveto</a></nav>'
                body = menu + esche + card
            return 200, "<html><body>%s</body></html>" % body, "text/html"
        if path in ("/prodotto/acqua-1", "/vai/xyz-777"):
            return 200, "<html><body>%s</body></html>" % page_for(mode, gtin), "text/html"
        if path.startswith("/prodotto/uliveto-esca-") or path == "/prodotto/promo-menu":
            return 200, "<html><body><h1>Uliveto - altra cosa</h1><p>Nessun codice qui</p></body></html>", "text/html"
        return 404, "no", "text/plain"
    return router, hits


def off_router(products=None, status=200, hits=None):
    hits = hits if hits is not None else []
    products = products or {}

    def router(path, q, base):
        hits.append(path)
        if status != 200:
            return status, "giù", "text/plain"
        code = path.rsplit("/", 1)[-1].replace(".json", "")
        if code in products:
            return 200, json.dumps({"status": 1, "product": products[code]}), "application/json"
        return 200, json.dumps({"status": 0, "status_verbose": "product not found"}), "application/json"
    return router, hits


def shopping_router(results=None, hits=None, status=200, error=None):
    """Finto SerpApi (Google Shopping). results: {'<query>': [risultati], '*': [risultati per qualunque query]}."""
    hits = hits if hits is not None else []
    results = results or {}

    def router(path, q, base):
        term = (q.get("q") or [""])[0]
        hits.append({"path": path, "q": term, "key": (q.get("api_key") or [""])[0]})
        if status != 200:
            return status, json.dumps({"error": error or "errore"}), "application/json"
        items = results.get(term, results.get("*", []))
        if not items:
            return 200, json.dumps({"error": "Google hasn't returned any results for this query."}), "application/json"
        return 200, json.dumps({"shopping_results": items}), "application/json"
    return router, hits


def shop_item(store, price, title="Acqua Uliveto 1,5 L", url=None):
    return {"title": title, "source": store, "price": f"€ {price:.2f}".replace(".", ","), "extracted_price": price,
            "link": url or f"https://{store.lower().replace(' ', '')}.example/p/uliveto"}
