from pvcore.gtin import normalize_gtin

from . import catalogs, products, stores
from .db import now_iso
from .limits import LEVEL_LABELS, build_limits

SCHEMA = 1
MAX_OTHER_CHAINS = 8


def _catalog_item(e):
    return {"chain": e["chain"], "level": e["level"], "level_label": LEVEL_LABELS.get(e["level"], ""),
            "url": e["url"], "title": e["title"], "price": e["price"], "currency": e["currency"],
            "verified_at": e["verified_at"]}


def run_scan(conn, raw_code, lat, lon, radius_km, settings, fetcher, robots) -> dict:
    gtin = normalize_gtin(raw_code)
    if gtin is None:
        raise ValueError("codice a barre non valido")
    radius_km = max(1.0, min(float(radius_km or settings.default_radius_km), settings.max_radius_km))
    product = products.lookup(conn, gtin, settings, fetcher)

    # Verifica sui cataloghi: solo se mai fatta (o scaduta). Il resto è lettura dal database.
    state, summary = "completata", {"provate": 0, "confermate": 0, "incomplete": 0}
    profiles = catalogs.usable_profiles(conn)
    consultable = len({p["chain"] for p in profiles})
    pending = False
    if not profiles:
        state = "non_disponibile"
    elif catalogs.needs_index(conn, gtin, settings.catalog_ttl_days):
        summary = catalogs.index_gtin(conn, gtin, product, fetcher, robots, settings.index_budget_s)
        if summary["incomplete"]:
            state, pending = "parziale", True
            conn.execute("INSERT OR IGNORE INTO index_queue VALUES(?,?)", (gtin, now_iso()))
            conn.commit()
    ev = catalogs.fresh_evidence(conn, gtin, settings.catalog_ttl_days)

    # Negozi: solo catene con una prova (livello 1-3). Le altre sono "senza informazioni".
    basis = {e["chain"]: e for e in ev}
    own = product.get("own_brand_chain")
    if own and own not in basis:
        basis[own] = {"chain": own, "level": 3, "url": None}
    near, with_info, without = [], [], []
    position_used = lat is not None and lon is not None
    if position_used:
        near = stores.nearby(conn, lat, lon, radius_km)
        per_chain = {}
        for s in near:
            c = s["chain"]
            if c in basis:
                if per_chain.get(c, 0) < 2:
                    per_chain[c] = per_chain.get(c, 0) + 1
                    b = basis[c]
                    with_info.append({"chain": c, "name": s["name"] or s["brand"], "distance_m": s["distance_m"],
                                      "address": s["address"], "opening_hours": s["opening_hours"],
                                      "lat": s["lat"], "lon": s["lon"],
                                      "basis": {"level": b["level"], "label": LEVEL_LABELS.get(b["level"], ""),
                                                "url": b.get("url"), "price": b.get("price"),
                                                "currency": b.get("currency")}})
        seen = set(basis)
        for s in near:
            c = s["chain"] or (s["name"] or s["brand"])
            if c in seen:
                continue
            seen.add(c)
            if len(without) < MAX_OTHER_CHAINS:
                without.append({"chain": s["chain"], "name": s["name"] or s["brand"], "distance_m": s["distance_m"],
                                "address": s["address"], "lat": s["lat"], "lon": s["lon"]})
    limits = build_limits(product_state=product["state"], has_catalogs=bool(ev),
                          indexing={"state": state, "chains_consultable": consultable},
                          stores_total=len(near), position_used=position_used,
                          source_error=product.get("source_error"), pending=pending,
                          chains_total=catalogs.physical_chain_count())
    return {
        "schema": SCHEMA, "gtin": gtin, "radius_km": radius_km, "position_used": position_used,
        "product": {"state": product["state"], "name": product["name"], "brand": product["brand"],
                    "quantity": product["quantity"], "image_url": product["image_url"], "source": product["source"],
                    "own_brand_chain": own, "corrected_fields": product["corrected_fields"]},
        "catalogs": [_catalog_item(e) for e in ev],
        "stores_with_product_in_catalog": with_info,
        "stores_without_information": without,
        "indexing": {"state": state, "chains_consultable": consultable, "chains_tried": summary["provate"],
                     "chains_confirmed": len(ev)},
        "limits": limits,
    }
