"""La sonda, provata contro siti finti in locale (nessuna rete esterna)."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import page
from probe.probe import (Fetcher, Robots, brand_tokens, probe_site, render_summary, run_sites,
                         targets_from_registry)
from pvcore.registry import load_registry

P = {"gtin": "8008490000021", "brand": "Uliveto", "name": "Acqua Minerale Naturale Uliveto", "quantity": "1500ml"}
HOME = '<html><body><h1>Shop</h1><form action="/cerca" method="get"><input type="search" name="q"></form></body></html>'
HOME_POST = HOME.replace('method="get"', 'method="post"')
RESULTS = ('<html><body><a href="/prodotto/acqua-uliveto-15l">Acqua Uliveto 1,5 L</a>'
           '<a href="/prodotto/altro-prodotto">Altro</a><a href="/chi-siamo">Uliveto chi siamo</a></body></html>')
EMPTY = "<html><body>Nessun risultato</body></html>"
HTML = "text/html; charset=utf-8"


def serve(router):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            status, body = router(u.path, parse_qs(u.query))
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", HTML)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def site(product_page="product_jsonld.html", robots="User-agent: *\nDisallow: /admin", home=HOME,
         by_code=True, by_name=False, home_status=200):
    def router(path, q):
        if path == "/robots.txt":
            return 200, robots
        if path == "/":
            return home_status, home
        if path == "/cerca":
            term = (q.get("q") or [""])[0]
            if (term == P["gtin"] and by_code) or (term != P["gtin"] and "uliveto" in term.lower() and by_name):
                return 200, RESULTS
            return 200, EMPTY
        if path == "/prodotto/acqua-uliveto-15l":
            return 200, page(product_page)
        return 404, "no"
    return router


@pytest.fixture
def run():
    servers = []

    def _run(router, name="finto"):
        srv, base = serve(router)
        servers.append(srv)
        f = Fetcher(min_interval=0, timeout=3)
        return probe_site({"name": name, "base": base}, [P], f, Robots(f))

    yield _run
    for s in servers:
        s.shutdown()


def outcome(r):
    return r["prodotti"][0]["per_codice"].get("outcome")


def test_structured_confirmation(run):
    r = run(site())
    assert r["esito"] == "codice_structured" and outcome(r) == "codice_structured"
    d = r["prodotti"][0]["per_codice"]
    assert d["identita_titolo_ok"] is True and d["scheda_elenco"] is False


def test_text_only_confirmation(run):
    assert run(site("product_text_only.html"))["esito"] == "codice_text"


def test_embedded_json_confirmation(run):
    assert run(site("product_nextdata.html"))["esito"] == "codice_embedded_json"


def test_page_without_code(run):
    assert run(site("no_code.html"))["esito"] == "scheda_senza_codice"


def test_blocked_page_is_not_a_confirmation(run):
    assert run(site("blocked.html"))["esito"] == "bloccato"


def test_robots_disallow_search_is_respected(run):
    r = run(site(robots="User-agent: *\nDisallow: /cerca"))
    assert r["esito"] == "robots_vieta_ricerca"


def test_robots_disallow_all(run):
    assert run(site(robots="User-agent: *\nDisallow: /"))["esito"] == "robots_vieta_tutto"


def test_home_403_is_blocked(run):
    assert run(site(home_status=403))["esito"] == "bloccato"


def test_js_shell_without_form(run):
    shell = page("js_shell.html")
    assert run(site(home=shell))["esito"] == "js_senza_form_ricerca"


def test_post_form_is_not_used(run):
    assert run(site(home=HOME_POST))["esito"] == "ricerca_solo_post"


def test_falls_back_to_name_search(run):
    r = run(site(by_code=False, by_name=True))
    assert r["prodotti"][0]["per_codice"]["outcome"] == "nessun_candidato"
    assert r["prodotti"][0]["per_nome"]["outcome"] == "codice_structured"
    assert r["esito"] == "codice_structured"


def test_no_results_anywhere(run):
    assert run(site(by_code=False, by_name=False))["esito"] == "nessun_candidato"


def test_unreachable_host():
    f = Fetcher(min_interval=0, timeout=2)
    r = probe_site({"name": "morto", "base": "http://127.0.0.1:1/"}, [P], f, Robots(f))
    # robots non leggibile: quasi sempre un firewall, non un divieto; la sonda non insiste
    assert r["esito"] == "bloccato_waf_o_robots_illeggibile"


def test_run_sites_never_raises_and_summary_renders():
    f = Fetcher(min_interval=0, timeout=2)
    srv, base = serve(site())
    try:
        res = run_sites([{"name": "ok", "base": base}, {"name": "morto", "base": "http://127.0.0.1:1/"}],
                        [P], f, workers=2)
    finally:
        srv.shutdown()
    assert {r["nome"] for r in res} == {"ok", "morto"}
    md = render_summary({"generato": "x", "siti": res, "richieste": f.requests_made})
    assert "codice_structured" in md and "| ok |" in md


def test_targets_from_registry():
    t = targets_from_registry(load_registry(), [{"name": "Extra", "base": "https://extra.example/"}])
    bases = [x["base"] for x in t]
    assert len(bases) == len(set(bases))
    assert any("it.everli.com/it/spesa/md/" in b for b in bases)
    assert any(b == "https://www.cosicomodo.it/mercato" for b in bases)
    assert not any("cicalia" in b for b in bases)           # solo online: non è un negozio vicino
    assert t[-1]["in_registro"] is False


def test_brand_tokens():
    assert brand_tokens("Uliveto") == ["ulivet"]
    assert "sant" in brand_tokens("Sant'Anna")
