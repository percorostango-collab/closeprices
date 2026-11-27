"""Prezzi online (Google Shopping) e somiglianze per nome: cosa deve comparire, cosa NO, e come lo si dichiara."""
import pytest
from helpers import G, serve2, shop_item, shopping_router
from probe.probe import Fetcher
from scenarios import KEY, LAT, LON, env
from server import offers
from server.config import Settings
from server.db import connect

pytestmark = pytest.mark.usefixtures("db_mode")
Q = dict(lat=LAT, lon=LON)
P = {"brand": "Uliveto", "name": "Acqua minerale naturale", "quantity": "1,5 l"}


def codes(r):
    return {x["code"] for x in r["limits"]}


# ------------------------------------------------------------------ funzioni pure (una sola volta)
@pytest.mark.parametrize("raw,expected", [("€ 0,89", 0.89), ("0,89 €", 0.89), ("EUR 1.299,00", 1299.0), ("1,299.00", 1299.0),
                                          ("2.50", 2.5), ("da 3,99 €", 3.99), ("gratis", None), (None, None), (0, None), (-3, None)])
def test_parse_price(raw, expected):
    assert offers.parse_price(raw) == expected


def test_normalize_filters_dedupes_and_sorts():
    raw = [shop_item("Esselunga", 1.10), shop_item("Esselunga", 0.95), shop_item("Conad", 0.89),
           shop_item("Amazon", 0.70, title="Acqua Uliveto 0,5 L"),              # formato diverso
           shop_item("eBay", 0.60, title="Acqua Uliveto Zero 1,5 L"),           # variante in più
           shop_item("Lidl", 0.50, title="Acqua Sant'Anna 1,5 L"),              # altra marca
           shop_item("MediaWorld", 0.40, title="Acqua Uliveto 1,5 L x 6"),      # confezione diversa
           {"title": "Acqua Uliveto 1,5 L", "source": "SenzaLink", "extracted_price": 0.5, "link": ""},
           {"title": "Acqua Uliveto 1,5 L", "source": "SenzaPrezzo", "link": "https://x.example/p"}]
    out = offers.normalize(raw, P, "codice")
    assert [(o["store"], o["price"]) for o in out] == [("Conad", 0.89), ("Esselunga", 0.95)]
    assert all(o["match"] == "codice" and o["currency"] == "EUR" for o in out)


def test_normalize_unknown_product_keeps_everything_valid():
    out = offers.normalize([shop_item("Conad", 0.89, title="Roba qualsiasi")], {}, "codice")
    assert len(out) == 1


def test_api_key_never_leaks_from_errors():
    assert "SEGRETO" not in offers._clean("url /search.json?q=1&api_key=SEGRETO&gl=it", "SEGRETO")
    assert "SEGRETO" not in offers._clean("errore SEGRETO qui", "SEGRETO")


# ------------------------------------------------------------------ la ricerca contro un finto SerpApi
def run_search(results=None, status=200, error=None, product=P, key="K123"):
    router, hits = shopping_router(results, status=status, error=error)
    srv, base = serve2(router)
    try:
        s = Settings(serpapi_key=key, serpapi_base=base.rstrip("/"), request_interval_s=0)
        return offers.search(G, product, s, Fetcher(min_interval=0, timeout=3, ua="T")), hits
    finally:
        srv.shutdown()


def test_search_by_code_first_and_only_one_call_when_it_works():
    out, hits = run_search({G: [shop_item("Conad", 0.89)]})
    assert out["state"] == "ok" and out["offers"][0]["match"] == "codice" and out["searches"] == 1
    assert [h["q"] for h in hits] == [G] and out["name_hint"] == "Acqua Uliveto 1,5 L"


def test_search_falls_back_to_name_and_says_so():
    name_q = "Uliveto Acqua minerale naturale 1,5 l"
    out, hits = run_search({name_q: [shop_item("Esselunga", 0.99)]})
    assert out["state"] == "ok" and out["offers"][0]["match"] == "nome" and out["searches"] == 2
    assert [h["q"] for h in hits] == [G, name_q]


def test_search_with_nothing_found():
    out, _ = run_search({})
    assert out["state"] == "nessun_risultato" and out["offers"] == []


@pytest.mark.parametrize("status,error,state", [(429, "Your account has run out of searches.", "quota_esaurita"),
                                                (200, None, "ok"), (401, "Invalid API key.", "errore"),
                                                (500, "boom", "errore")])
def test_search_error_states(status, error, state):
    out, _ = run_search({"*": [shop_item("Conad", 0.89)]}, status=status, error=error)
    assert out["state"] == state
    if state != "ok":
        assert out["offers"] == [] and "K123" not in str(out)


def test_search_network_down_is_an_error_without_the_key():
    s = Settings(serpapi_key="K-SEGRETA-999", serpapi_base="http://127.0.0.1:1", request_interval_s=0)
    out = offers.search(G, P, s, Fetcher(min_interval=0, timeout=2, ua="T"))
    assert out["state"] == "errore" and "K-SEGRETA-999" not in str(out)


# ------------------------------------------------------------------ cache e quota (database)
def test_plan_cache_quota_and_failed_searches_are_not_cached(tmp_path):
    conn = connect(str(tmp_path / "o.db"))
    s = Settings(serpapi_key="K", shopping_monthly_limit=3)
    assert offers.plan(conn, G, Settings(serpapi_key=""))["state"] == "non_configurato"
    assert offers.plan(conn, G, s)["action"] == "search"
    res = {"state": "ok", "searches": 2, "name_hint": "x", "offers": [{"store": "Conad", "title": "Acqua Uliveto", "price": 0.89, "currency": "EUR",
                                                    "url": "https://conad.example/p/1", "match": "codice", "source": offers.SOURCE}]}
    offers.save(conn, G, res)
    p = offers.plan(conn, G, s)
    assert p["action"] == "cache" and p["offers"][0]["store"] == "Conad" and offers.usage(conn) == 2
    # errore momentaneo: si conta la chiamata ma NON si memorizza "nessun risultato"
    offers.save(conn, "8020141800002", {"state": "errore", "searches": 1, "name_hint": None, "offers": []})
    assert offers.plan(conn, "8020141800002", s)["state"] == "quota_esaurita"       # 3 usate su 3
    assert offers.plan(conn, "8020141800002", Settings(serpapi_key="K", shopping_monthly_limit=50))["action"] == "search"
    # la cache vale anche a quota finita
    assert offers.plan(conn, G, s)["action"] == "cache"


# ------------------------------------------------------------------ scenari completi attraverso l'API
def test_scan_shows_online_prices_sorted_and_cached():
    with env(shopping={G: [shop_item("Esselunga", 0.99), shop_item("Conad", 0.89), shop_item("Amazon", 1.20)]}) as (c, ctx):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert [(o["store"], o["price"], o["match"]) for o in r["online_offers"]] == [
            ("Conad", 0.89, "codice"), ("Esselunga", 0.99, "codice"), ("Amazon", 1.2, "codice")]
        assert r["online_offers_state"]["state"] == "ok" and r["online_offers_state"]["searches_used_month"] == 1
        assert "OFFERS_INFO" in codes(r) and "OFFERS_NOT_CONFIGURED" not in codes(r)
        n = len(ctx["shopping"])
        r2 = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert len(ctx["shopping"]) == n and r2["online_offers"] == r["online_offers"]       # cache: nessuna nuova ricerca
        assert r2["online_offers_state"]["searches_used_month"] == 1


def test_scan_name_match_is_declared():
    with env(shopping={"Uliveto Acqua Minerale Naturale 1,5 L": [shop_item("Esselunga", 0.99)]}) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["online_offers"][0]["match"] == "nome" and r["online_offers_state"]["searches_used_month"] == 2
        assert "per somiglianza di nome" in next(x["text"] for x in r["limits"] if x["code"] == "OFFERS_INFO")


def test_scan_without_key_says_prices_are_off():
    with env() as (c, ctx):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["online_offers"] == [] and r["online_offers_state"]["state"] == "non_configurato"
        assert "OFFERS_NOT_CONFIGURED" in codes(r) and ctx["shopping"] == []


def test_scan_quota_exhausted_makes_no_call():
    with env(shopping={G: [shop_item("Conad", 0.89)]}, shopping_limit=0) as (c, ctx):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["online_offers_state"]["state"] == "quota_esaurita" and ctx["shopping"] == []
        assert "OFFERS_QUOTA" in codes(r)


def test_scan_survives_a_failing_price_service_and_hides_the_key():
    with env(shopping={}, shopping_status=500, shopping_error="boom") as (c, _):
        resp = c.get("/v1/scan", params={"code": G, **Q})
        assert resp.status_code == 200
        r = resp.json()
        assert r["online_offers_state"]["state"] == "errore" and "OFFERS_ERROR" in codes(r) and KEY not in resp.text
        assert r["product"]["state"] == "riconosciuto"          # il resto della scansione funziona


def test_unknown_product_gets_a_name_hint_from_shopping_but_is_still_unrecognized():
    with env(off_products={}, shopping={"*": [shop_item("Conad", 0.89, title="Qualcosa di misterioso 500 g")]}) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["product"]["state"] == "non_riconosciuto" and r["product"]["name"] is None
        assert r["product"]["name_hint"] == "Qualcosa di misterioso 500 g" and "non verificato" in r["product"]["name_hint_source"]
        assert len(r["online_offers"]) == 1                       # senza un nome noto non si può filtrare: resta dichiarato


def test_recognized_product_never_gets_a_hint():
    with env(shopping={G: [shop_item("Conad", 0.89)]}) as (c, _):
        assert c.get("/v1/scan", params={"code": G, **Q}).json()["product"]["name_hint"] is None


# ------------------------------------------------------------------ somiglianze per nome nei cataloghi
def test_catalog_name_match_is_shown_apart_and_unlocks_no_stores():
    with env(mode="nocode", by_name=True) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["catalogs"] == [] and r["stores_with_product_in_catalog"] == []          # nessuna PROVA
        m = r["catalog_name_matches"]
        assert len(m) == 1 and m[0]["chain"] == "Conad" and m[0]["level"] == 5 and "NON verificata" in m[0]["level_label"]
        assert "NAME_MATCH_INFO" in codes(r) and "NO_CATALOG_CONFIRMATION" in codes(r)
        assert r["indexing"]["chains_confirmed"] == 0


def test_catalog_name_match_rejects_a_variant():
    with env(mode="nocode_variant", by_name=True) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert r["catalog_name_matches"] == [] and "NAME_MATCH_INFO" not in codes(r)


def test_barcode_proof_wins_over_name_match():
    with env(mode="json", by_name=True) as (c, _):
        r = c.get("/v1/scan", params={"code": G, **Q}).json()
        assert [x["level"] for x in r["catalogs"]] == [1] and r["catalog_name_matches"] == []
