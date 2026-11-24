"""Campione automatico di prodotti italiani da Open Food Facts: nessun inserimento a mano.

Italiano = prefisso GS1 800-839 (il paese del produttore). Ordinati per numero di scansioni,
così sono prodotti che la gente compra davvero. Massimo 2 per marca, formato leggibile."""
import json
import os

from pvcore.gtin import normalize_gtin
from pvcore.identity import sizes

OFF_BASE = os.environ.get("OFF_BASE", "https://world.openfoodfacts.org")
FIELDS = "code,product_name,product_name_it,brands,quantity,unique_scans_n"


def is_italian_prefix(code: str) -> bool:
    return len(code) == 13 and code.isdigit() and 800 <= int(code[:3]) <= 839


def pick(products, chosen, per_brand, n):
    for p in products:
        code = normalize_gtin(str(p.get("code", "")))
        brand = (p.get("brands") or "").split(",")[0].strip()
        name = (p.get("product_name_it") or p.get("product_name") or "").strip()
        qty = (p.get("quantity") or "").strip()
        if not (code and is_italian_prefix(code) and brand and name and qty and sizes(qty)):
            continue
        if any(c["gtin"] == code for c in chosen) or per_brand.get(brand.lower(), 0) >= 2:
            continue
        per_brand[brand.lower()] = per_brand.get(brand.lower(), 0) + 1
        chosen.append({"gtin": code, "brand": brand, "name": name, "quantity": qty, "probe": True,
                       "origine": "Open Food Facts, italiani più scansionati"})
        if len(chosen) >= n:
            break


def make_sample(fetcher, n=12, pages=8, base=None):
    """fetcher: Fetcher con pausa lunga (Open Food Facts limita le ricerche a ~10/minuto)."""
    base = base or OFF_BASE
    chosen, per_brand, log = [], {}, []
    for page in range(1, pages + 1):
        r = fetcher.get(base + "/cgi/search.pl", params={
            "action": "process", "json": 1, "tagtype_0": "countries", "tag_contains_0": "contains",
            "tag_0": "italy", "sort_by": "unique_scans_n", "page_size": 100, "page": page, "fields": FIELDS})
        try:
            prods = json.loads(r.text).get("products") or []
        except Exception:
            prods = []
        before = len(chosen)
        if prods:
            pick(prods, chosen, per_brand, n)
        log.append(f"pagina {page}: HTTP {r.status}, {len(prods)} prodotti, scelti {len(chosen) - before} (totale {len(chosen)})")
        if not prods or len(chosen) >= n:
            break
    return chosen, log
