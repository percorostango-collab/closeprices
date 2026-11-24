import json

import pytest
from helpers import G, catalog_router, off_router, serve2
from probe.probe import Fetcher, Robots
from server import catalogs, products, stores
from server.chains import classify
from server.config import Settings
from server.db import connect


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def settings(tmp_path, off_base="http://127.0.0.1:1"):
    return Settings(db_path=str(tmp_path / "t.db"), off_base=off_base.rstrip("/"), request_interval_s=0,
                    correction_min_users=3, contact="test@example.org")


# ------------------------------------------------------------------------ catene
@pytest.mark.parametrize("brand,name,expected", [
    ("Conad City", "Conad City", "Conad"), (None, "MD Discount", "MD"), (None, "MDX bar", None),
    ("Despar", "Interspar Roma", "Despar"), (None, "Super Elite Rimini", "Elite"), (None, "Da Mario", None),
    (None, "Dem Supermercati", "Dem"), (None, "Pewex Prontospesa", "Pewex"), ("Eurospin", None, "Eurospin")])
def test_classify(brand, name, expected):
    assert classify(brand, name) == expected


# ------------------------------------------------------------------------ negozi
def el(i, name=None, brand=None, wd=None, lat=41.9028, lon=12.4964, typ="node"):
    tags = {"shop": "supermarket"}
    for k, v in (("name", name), ("brand", brand), ("brand:wikidata", wd)):
        if v:
            tags[k] = v
    e = {"type": typ, "id": i, "tags": tags}
    if typ == "node":
        e.update(lat=lat, lon=lon)
    else:
        e["center"] = {"lat": lat, "lon": lon}
    return e


def test_parse_and_upsert_idempotent(conn):
    data = {"elements": [el(1, "Conad City", "Conad"), el(2, typ="way", name="Lidl", lat=41.91),
                         el(3), {"type": "node", "id": 4, "tags": {"name": "x"}}]}      # senza nome / senza coordinate
    rows = stores.parse_overpass(data)
    assert [r["osm_id"] for r in rows] == [1, 2]
    stores.upsert(conn, rows)
    stores.upsert(conn, rows)
    assert conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 2
    assert conn.execute("SELECT chain FROM stores WHERE osm_id=2").fetchone()[0] == "Lidl"


def test_wikidata_learning(conn):
    els = [el(i, f"Conad {i}", "Conad", "Q1", lat=41.9 + i / 1000) for i in range(1, 4)]
    els.append(el(10, "Il Mio Market", None, "Q1"))                       # stesso identificativo, nome libero
    els += [el(20, "Alfa", None, "Q2"), el(21, "Conad X", "Conad", "Q2"), el(22, "Lidl Y", "Lidl", "Q2"),
            el(23, "Senza nome noto", None, "Q2")]                        # gruppo diviso 50/50: non si propaga
    els += [el(30, "Mini", None, "Q3"), el(31, "Mini2", None, "Q3")]      # troppo piccolo
    stores.upsert(conn, stores.parse_overpass({"elements": els}))
    assert stores.propagate_wikidata(conn) == 1
    chain = lambda i: conn.execute("SELECT chain FROM stores WHERE osm_id=?", (i,)).fetchone()[0]  # noqa: E731
    assert chain(10) == "Conad" and chain(20) is None and chain(23) is None and chain(30) is None


def test_haversine_and_nearby(conn):
    assert 186_000 < stores.haversine_m(41.9028, 12.4964, 40.8518, 14.2681) < 192_000     # Roma-Napoli
    els = [el(1, "Conad A", "Conad", lat=41.9060, lon=12.4964), el(2, "Lidl B", None, lat=41.9028, lon=12.5100),
           el(3, "Esselunga C", None, lat=41.99, lon=12.4964)]
    stores.upsert(conn, stores.parse_overpass({"elements": els}))
    near = stores.nearby(conn, 41.9028, 12.4964, 5)
    assert [s["chain"] for s in near] == ["Conad", "Lidl"] and near[0]["distance_m"] < near[1]["distance_m"]
    assert len(stores.nearby(conn, 41.9028, 12.4964, 15)) == 3
    assert [s["chain"] for s in stores.nearby(conn, 41.9028, 12.4964, 15, chains=["Esselunga"])] == ["Esselunga"]
    assert stores.nearby(conn, 41.9028, 12.4964, 15, chains=[]) == []


def test_tiles_cover_italy():
    t = list(stores.tiles())
    assert 30 <= len(t) <= 60 and all(a[0] < a[2] and a[1] < a[3] for a in t)


# ------------------------------------------------------------------------ prodotti
OFFP = {G: {"product_name": "Acqua Minerale", "brands": "Uliveto,Altro", "quantity": "1,5 L", "image_front_small_url": "http://i/x.jpg"}}


def test_product_found_is_cached(conn, tmp_path):
    router, hits = off_router(OFFP)
    srv, base = serve2(router)
    try:
        s = settings(tmp_path, base)
        f = Fetcher(min_interval=0, timeout=3, ua=s.user_agent)
        a = products.lookup(conn, G, s, f)
        n = len(hits)
        b = products.lookup(conn, G, s, f)
    finally:
        srv.shutdown()
    assert a["state"] == "riconosciuto" and a["brand"] == "Uliveto" and a["source"] == "Open Food Facts"
    assert len(hits) == n == 1 and b["name"] == "Acqua Minerale"


def test_product_missing_is_cached_but_outage_is_not(conn, tmp_path):
    router, hits = off_router({})
    srv, base = serve2(router)
    try:
        s = settings(tmp_path, base)
        f = Fetcher(min_interval=0, timeout=3, ua=s.user_agent)
        assert products.lookup(conn, "8020141800002", s, f)["state"] == "non_riconosciuto"
        products.lookup(conn, "8020141800002", s, f)
    finally:
        srv.shutdown()
    assert len(hits) == 1
    router, hits = off_router({}, status=503)
    srv, base = serve2(router)
    try:
        s = settings(tmp_path, base)
        f = Fetcher(min_interval=0, timeout=3, ua=s.user_agent)
        r = products.lookup(conn, "8001620014172", s, f)
        products.lookup(conn, "8001620014172", s, f)
    finally:
        srv.shutdown()
    assert r["state"] == "errore_fonte" and "503" in r["source_error"] and len(hits) == 2   # niente "non trovato" memorizzato


def test_corrections_need_three_distinct_users(conn, tmp_path):
    router, _ = off_router({})
    srv, base = serve2(router)
    try:
        s = settings(tmp_path, base)
        f = Fetcher(min_interval=0, timeout=3, ua=s.user_agent)
        code = "8020141800002"
        for u in ("u1", "u1", "u2"):
            products.add_correction(conn, code, "name", "Acqua Sant'Anna", u)
        assert products.lookup(conn, code, s, f)["state"] == "non_riconosciuto"
        products.add_correction(conn, code, "name", "acqua  sant'anna", "u3")
        r = products.lookup(conn, code, s, f)
    finally:
        srv.shutdown()
    assert r["state"] == "riconosciuto" and r["source"] == "Correzioni degli utenti" and r["corrected_fields"] == ["name"]


@pytest.mark.parametrize("args", [("123", "name", "x", "u"), ("8020141800002", "gtin", "x", "u"),
                                  ("8020141800002", "name", "", "u"), ("8020141800002", "name", "x" * 200, "u"),
                                  ("8020141800002", "name", "x", "")])
def test_correction_validation(conn, args):
    with pytest.raises(ValueError):
        products.add_correction(conn, *args)


def test_own_brand_hint(conn, tmp_path):
    router, _ = off_router({})
    srv, base = serve2(router)
    try:
        s = settings(tmp_path, base)
        r = products.lookup(conn, "8017596003126", s, Fetcher(min_interval=0, timeout=3, ua=s.user_agent))
    finally:
        srv.shutdown()
    assert r["own_brand_chain"] == "Eurospin"


# ------------------------------------------------------------------------ cataloghi: scoperta
def disc(router, **kw):
    srv, base = serve2(router)
    try:
        f = Fetcher(min_interval=0, timeout=3, ua="Test/1.0")
        return catalogs.discover_site({"chain": "X", "name": "X", "base": base}, f, Robots(f))
    finally:
        srv.shutdown()


def test_discover_usable_and_blocked_and_others():
    assert disc(catalog_router()[0])["status"] == "usabile"
    r = disc(lambda p, q, b: (403, "x", "text/plain"))
    assert r["status"] == "bloccato"
    assert disc(catalog_router(robots="User-agent: *\nDisallow: /")[0])["status"] == "robots_vieta"
    assert disc(catalog_router(home='<html><body><div id="root"></div></body></html>')[0])["status"] == "js_senza_ricerca"
    assert disc(catalog_router(home=catalog_router.__globals__["FORM"].replace('method="get"', 'method="post"'))[0])["status"] == "ricerca_post"
    assert disc(catalog_router(home="<html><body>Benvenuti</body></html>")[0])["status"] == "senza_ricerca"
