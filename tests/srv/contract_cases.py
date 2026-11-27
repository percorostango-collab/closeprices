"""Scenari da cui nascono gli esempi di risposta per l'app (tests/fixtures/api)."""
from helpers import G, shop_item
from scenarios import LAT, LON

NAME_Q = "Uliveto Acqua Minerale Naturale 1,5 L"
CASES = {
    "scan_full": (dict(shopping={G: [shop_item("Esselunga", 0.99), shop_item("Conad", 0.89)]}), dict(code=G, lat=LAT, lon=LON)),
    "scan_unknown": (dict(off_products={}, shopping={"*": [shop_item("Conad", 0.89, title="Qualcosa di misterioso 500 g")]}),
                     dict(code="8020141800002", lat=LAT, lon=LON)),
    "scan_own_brand": (dict(off_products={}), dict(code="8017596003126", lat=LAT, lon=LON)),
    "scan_no_position": (dict(), dict(code=G)),
    "scan_no_catalogs": (dict(with_profile=False), dict(code=G, lat=LAT, lon=LON)),
    "scan_name_match": (dict(mode="nocode", by_name=True, shopping={NAME_Q: [shop_item("Esselunga", 0.99)]}),
                        dict(code=G, lat=LAT, lon=LON)),
}
