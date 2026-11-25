import time

import pytest
from helpers import G
from scenarios import LAT, LON, env

pytestmark = pytest.mark.usefixtures("db_mode")

Q = dict(lat=LAT, lon=LON)


def codes(r):
    return {x["code"] for x in r["limits"]}


def test_full_scan_with_catalog_proof():
    with env() as (c, ctx):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["product"]["state"] == "riconosciuto" and r["product"]["brand"] == "Uliveto"
        assert r["product"]["source"] == "Open Food Facts"
        assert [(x["chain"], x["level"], x["price"]) for x in r["catalogs"]] == [("Conad", 1, 0.89)]
        assert r["indexing"] == {"state": "completata", "chains_consultable": 1, "chains_tried": 1, "chains_confirmed": 1}
        # negozi con prova: SOLO Conad, i 2 più vicini, in ordine di distanza
        w = r["stores_with_product_in_catalog"]
        assert [x["name"] for x in w] == ["Conad City", "Conad Superstore"]
        assert w[0]["distance_m"] < w[1]["distance_m"] < 1200 and w[0]["basis"]["level"] == 1
        assert w[0]["address"] == "Via Prova 1"
        # le altre catene sono "senza informazioni", Conad non ci compare
        wo = [x["chain"] for x in r["stores_without_information"]]
        assert "Conad" not in wo and {"Lidl", "Eurospin", "Esselunga"} <= set(wo) and None in wo
        assert {"COVERAGE", "STORE_AVAILABILITY", "PRICE_STORE"} <= codes(r)
        assert "NO_CATALOG_CONFIRMATION" not in codes(r) and "PRODUCT_NOT_RECOGNIZED" not in codes(r)
        # seconda scansione: nessuna nuova richiesta al catalogo
        n_cat, n_off = len(ctx["catalog"]), len(ctx["off"])
        r2 = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert len(ctx["catalog"]) == n_cat and len(ctx["off"]) == n_off and r2["catalogs"] == r["catalogs"]


def test_price_of_the_store_is_never_invented():
    with env() as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        for s in r["stores_with_product_in_catalog"]:
            assert s["basis"]["price"] == 0.89          # è il prezzo del CATALOGO, dichiarato come tale
        assert any("non è un dato pubblico" in x["text"] for x in r["limits"] if x["code"] == "PRICE_STORE")
        assert all("price" not in s for s in r["stores_without_information"])


def test_unknown_product_says_so():
    with env(off_products={}) as (c, _):
        r = c.get("/v1/scan", params={"code": "8020141800002", **Q}).json()
        assert r["product"]["state"] == "non_riconosciuto" and r["product"]["name"] is None
        assert {"PRODUCT_NOT_RECOGNIZED", "NO_CATALOG_CONFIRMATION"} <= codes(r)
        assert r["catalogs"] == [] and r["stores_with_product_in_catalog"] == []


@pytest.mark.parametrize("mode", ["nocode", "othercode", "carousel"])
def test_catalog_without_the_code_gives_no_proof(mode):
    with env(mode=mode) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["catalogs"] == [] and r["stores_with_product_in_catalog"] == []
        assert "NO_CATALOG_CONFIRMATION" in codes(r)
        assert r["indexing"]["chains_tried"] == 1 and r["indexing"]["chains_confirmed"] == 0


def test_own_brand_is_probable_not_certain():
    with env(off_products={}) as (c, _):
        r = c.get("/v1/scan", params={"code": "8017596003126", **Q}).json()
        w = r["stores_with_product_in_catalog"]
        assert [x["chain"] for x in w] == ["Eurospin"] and w[0]["basis"]["level"] == 3
        assert w[0]["basis"]["label"].startswith("Probabile") and r["catalogs"] == []
        assert "NO_CATALOG_CONFIRMATION" in codes(r)


def test_no_position():
    with env() as (c, _):
        r = c.get("/v1/scan", params={"code": G}).json()
        assert r["position_used"] is False and "NO_POSITION" in codes(r)
        assert r["stores_with_product_in_catalog"] == [] and r["stores_without_information"] == []
        assert len(r["catalogs"]) == 1          # i cataloghi si vedono lo stesso


def test_no_stores_loaded_in_the_area():
    with env(stores_on=False) as (c, _):
        assert "STORES_EMPTY" in codes(c.get("/v1/scan", params={"code": G, **Q}).json())


def test_no_queryable_catalogs():
    with env(with_profile=False) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["indexing"]["state"] == "non_disponibile" and "NO_CATALOGS_QUERYABLE" in codes(r)
        assert "NO_CATALOG_CONFIRMATION" in codes(r)


def test_slow_catalog_is_partial_and_queued():
    with env(delay=2.0, budget=0.4) as (c, ctx):
        t0 = time.time()
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert time.time() - t0 < 1.8
        assert r["indexing"]["state"] == "parziale" and "INDEX_PARTIAL" in codes(r)
        from server.db import connect
        conn = connect(ctx["settings"].db_path, ctx["settings"])
        assert conn.execute("SELECT gtin FROM index_queue").fetchone()[0] == G


def test_validation():
    with env() as (c, _):
        assert c.get("/v1/scan", params={"code": "123"}).status_code == 400
        assert c.get("/v1/scan", params={"code": "8008490000022"}).status_code == 400      # cifra di controllo
        assert c.get("/v1/scan", params={"code": G, "lat": 95, "lon": 0}).status_code == 422
        assert c.get("/v1/scan", params={"code": G, **Q, "radius_km": 500}).json()["radius_km"] == 30
        assert c.get("/v1/scan", params={"code": G, **Q, "radius_km": 0.1}).json()["radius_km"] == 1


def test_corrections_flow_and_coverage():
    with env(off_products={}) as (c, _):
        code = "8020141800002"
        for u in ("a", "b"):
            assert c.post("/v1/corrections", json={"code": code, "field": "name", "value": "Acqua Sant'Anna", "user_id": u}).status_code == 200
        assert c.get("/v1/scan", params={"code": code, **Q}).json()["product"]["state"] == "non_riconosciuto"
        c.post("/v1/corrections", json={"code": code, "field": "name", "value": "Acqua Sant'Anna", "user_id": "c"})
        p = c.get("/v1/scan", params={"code": code, **Q}).json()["product"]
        assert p["state"] == "riconosciuto" and p["name"] == "Acqua Sant'Anna" and p["corrected_fields"] == ["name"]
        assert c.post("/v1/corrections", json={"code": code, "field": "x", "value": "y", "user_id": "a"}).status_code == 400
        cov = c.get("/v1/coverage").json()
        assert cov["negozi"]["totale"] == 7 and cov["cataloghi"]["catene_consultabili"] == 1
        assert cov["cataloghi"]["catene_con_negozi_fisici"] > 40


def test_health():
    with env() as (c, _):
        assert c.get("/v1/health").json() == {"ok": True}
