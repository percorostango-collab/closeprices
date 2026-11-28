"""Cuore del progetto: nell'indice entra SOLO ciò che il codice a barre conferma."""
import json

import pytest
from helpers import G, catalog_router, serve2
from probe.probe import Fetcher, Robots
from server import catalogs
from server.db import connect


def run(mode="json", gtin=G, product=None, budget=5.0, **kw):
    router, hits = catalog_router(mode, G, **kw)
    srv, base = serve2(router)
    try:
        import tempfile, os
        conn = connect(os.path.join(tempfile.mkdtemp(), "i.db"))
        f = Fetcher(min_interval=0, timeout=3, ua="Test/1.0")
        rb = Robots(f)
        target = {"chain": "Conad", "name": "Conad", "base": base}
        catalogs.save_profile(conn, target, catalogs.discover_site(target, f, rb))
        out = catalogs.index_gtin(conn, gtin, product or {}, f, rb, budget_s=budget)
        ev = [dict(r) for r in conn.execute("SELECT * FROM evidence")]
        att = {r["chain"]: r["outcome"] for r in conn.execute("SELECT * FROM attempts")}
        return out, ev, att, hits
    finally:
        srv.shutdown()


def test_structured_code_is_level_1_with_price():
    out, ev, att, _ = run("json")
    assert out["confermate"] == 1 and att == {"Conad": "confermato"}
    e = ev[0]
    assert e["level"] == 1 and e["price"] == 0.89 and e["currency"] == "EUR" and e["url"].endswith("/prodotto/acqua-1")


def test_text_code_is_level_2():
    assert run("text")[1][0]["level"] == 2


def test_known_brand_uses_it_to_pick_the_link():
    assert run("json", product={"brand": "Uliveto", "name": "Acqua"})[1][0]["level"] == 1


@pytest.mark.parametrize("mode,outcome", [("nocode", "scheda_senza_codice"), ("othercode", "scheda_senza_codice"),
                                          ("carousel", "scheda_senza_codice")])
def test_no_false_positives(mode, outcome):
    out, ev, att, _ = run(mode)
    assert ev == [] and out["confermate"] == 0 and att["Conad"] == outcome      # niente prove, niente indice


def test_code_not_found_in_search():
    out, ev, att, _ = run("json", gtin="8020141800002")
    assert ev == [] and att["Conad"] == "nessun_risultato"


def test_waf_on_search_is_recorded_not_guessed():
    out, ev, att, _ = run("json", search_status=403)
    assert ev == [] and att["Conad"] == "bloccato"


def test_robots_disallow_search_is_respected():
    router, hits = catalog_router("json", G, robots="User-agent: *\nDisallow: /cerca\n")
    srv, base = serve2(router)
    try:
        import tempfile, os
        conn = connect(os.path.join(tempfile.mkdtemp(), "r.db"))
        f = Fetcher(min_interval=0, timeout=3, ua="Test/1.0")
        # profilo scoperto quando il divieto non c'era ancora: ora robots lo vieta
        conn.execute("INSERT INTO site_profiles VALUES('Conad',?, 'usabile',?, 'q','{}','2026-01-01T00:00:00Z','')",
                     (base, base + "cerca"))
        out = catalogs.index_gtin(conn, G, {}, f, Robots(f))
        assert out["confermate"] == 0
        assert conn.execute("SELECT outcome FROM attempts").fetchone()[0] == "robots"
        assert "/cerca" not in hits
    finally:
        srv.shutdown()


def test_slow_site_does_not_block_the_scan_and_is_reported_incomplete():
    import time
    t0 = time.time()
    out, ev, att, _ = run("json", delay=2.0, budget=0.4)
    assert time.time() - t0 < 1.5 and out["incomplete"] == 1 and att == {} and ev == []


def test_no_profiles_means_nothing_is_tried():
    import tempfile, os
    conn = connect(os.path.join(tempfile.mkdtemp(), "e.db"))
    out = catalogs.index_gtin(conn, G, {}, Fetcher(min_interval=0, ua="T"), Robots(Fetcher(min_interval=0, ua="T")))
    assert out == {"consultabili": 0, "provate": 0, "confermate": 0, "somiglianze": 0, "incomplete": 0}


def test_needs_index_ttl():
    import tempfile, os
    conn = connect(os.path.join(tempfile.mkdtemp(), "n.db"))
    assert catalogs.needs_index(conn, G, 30)
    conn.execute("INSERT INTO attempts VALUES(?,?,?,?)", (G, "Conad", "confermato", "2026-11-20T00:00:00Z"))
    assert not catalogs.needs_index(conn, G, 30)
    conn.execute("UPDATE attempts SET tried_at='2020-01-01T00:00:00Z'")
    assert catalogs.needs_index(conn, G, 30)


# ---- il difetto trovato sul Todis reale: le "esche" prima della scheda giusta nascondevano il prodotto ----
def test_decoy_results_do_not_hide_the_right_card():
    out, ev, att, hits = run("json", product={"brand": "Uliveto", "name": "Acqua"}, decoys=4)
    assert out["confermate"] == 1 and att == {"Conad": "confermato"} and ev[0]["url"].endswith("/prodotto/acqua-1")


def test_card_link_is_found_even_without_a_product_path():
    out, ev, att, _ = run("json", odd_link=True)
    assert att == {"Conad": "confermato"} and ev[0]["url"].endswith("/vai/xyz-777")


def test_links_near_code_only_takes_the_card_not_the_menu():
    from bs4 import BeautifulSoup
    from server.catalogs import links_near_code
    html = ('<nav><a href="/prodotto/menu-1">Menu</a></nav>'
            '<div class="c"><span data-ean="8008490000021"></span><a href="/p/giusto">Giusto</a></div>'
            '<div class="c"><a href="/p/altro">Altro</a></div>')
    assert links_near_code(BeautifulSoup(html, "html.parser"), "https://x.example/", "8008490000021") == ["https://x.example/p/giusto"]
    # un blocco enorme (tutta la pagina) non va risalito: niente link presi a caso
    big = '<div><span data-ean="8008490000021"></span><a href="/p/x">x</a>' + "testo " * 400 + "</div>"
    assert links_near_code(BeautifulSoup(big, "html.parser"), "https://x.example/", "8008490000021") == []
    # un altro dominio non conta
    other = '<div data-ean="8008490000021"><a href="https://altro.example/p/1">x</a></div>'
    assert links_near_code(BeautifulSoup(other, "html.parser"), "https://x.example/", "8008490000021") == []
