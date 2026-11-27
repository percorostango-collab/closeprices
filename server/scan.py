from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout

from pvcore.gtin import normalize_gtin

from . import catalogs, offers, products, stores
from .db import now_iso
from .limits import LEVEL_LABELS, build_limits

SCHEMA = 1
MAX_OTHER_CHAINS = 8


def _catalog_item(e):
    return {"chain": e["chain"], "level": e["level"], "level_label": LEVEL_LABELS.get(e["level"], ""),
            "url": e["url"], "title": e["title"], "price": e["price"], "currency": e["currency"],
            "verified_at": e["verified_at"]}


def _offer_item(o):
    return {"store": o["store"], "title": o["title"], "price": o["price"], "currency": o["currency"], "url": o["url"],
            "match": o["match"], "source": o["source"]}


def run_scan(conn, raw_code, lat, lon, radius_km, settings, fetcher, robots) -> dict:
    gtin = normalize_gtin(raw_code)
    if gtin is None:
        raise ValueError("codice a barre non valido")
    radius_km = max(1.0, min(float(radius_km or settings.default_radius_km), settings.max_radius_km))
    product = products.lookup(conn, gtin, settings, fetcher)

    # Prezzi online: la cache si legge subito; se serve una ricerca parte in parallelo ai cataloghi (solo rete).
    op = offers.plan(conn, gtin, settings)
    pool, fut = None, None
    if op["action"] == "search":
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(offers.search, gtin, {k: product.get(k) for k in ("brand", "name", "quantity")}, settings, fetcher)

    # Verifica sui cataloghi: solo se mai fatta (o scaduta). Il resto è lettura dal database.
    state, summary = "completata", {"provate": 0, "confermate": 0, "somiglianze": 0, "incomplete": 0}
    profiles = catalogs.usable_profiles(conn)
    consultable = len({p["chain"] for p in profiles})
    pending = False
    if not profiles:
        state = "non_disponibile"
    elif catalogs.needs_index(conn, gtin, settings.catalog_ttl_days):
        if settings.index_budget_s <= 0:
            # modalità "solo coda": la scansione non interroga i cataloghi, li verifica la manutenzione
            state, pending = "parziale", True
            conn.execute("INSERT OR IGNORE INTO index_queue VALUES(?,?)", (gtin, now_iso()))
            conn.commit()
        else:
            summary = catalogs.index_gtin(conn, gtin, product, fetcher, robots, settings.index_budget_s)
        if summary["incomplete"]:
            state, pending = "parziale", True
            conn.execute("INSERT OR IGNORE INTO index_queue VALUES(?,?)", (gtin, now_iso()))
            conn.commit()

    # Prezzi online: raccolta dell'esito
    o_state, o_list, o_hint, o_error = op["state"], op["offers"], op.get("name_hint"), None
    if fut is not None:
        try:
            res = fut.result(timeout=settings.offers_timeout_s)
            offers.save(conn, gtin, res)
            o_state, o_list, o_hint, o_error = res["state"], res["offers"], res["name_hint"], res["error"]
        except FutTimeout:
            o_state, o_error = "errore", "tempo scaduto"
        pool.shutdown(wait=False)
    if o_state in ("quota_esaurita", "errore") and not o_list and op["action"] != "search":
        o_list = op["offers"]

    ev = catalogs.fresh_evidence(conn, gtin, settings.catalog_ttl_days)
    certain = [e for e in ev if e["level"] <= 2]
    certain_chains = {e["chain"] for e in certain}
    name_matches = [e for e in ev if e["level"] == 5 and e["chain"] not in certain_chains]

    # Negozi: solo catene con una PROVA (livello 1-3). Le somiglianze non sbloccano i negozi.
    basis = {e["chain"]: e for e in certain}
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
    used = offers.usage(conn) if settings.serpapi_key else 0
    limits = build_limits(product_state=product["state"], has_catalogs=bool(certain),
                          indexing={"state": state, "chains_consultable": consultable},
                          stores_total=len(near), position_used=position_used,
                          source_error=product.get("source_error"), pending=pending,
                          chains_total=catalogs.physical_chain_count(),
                          offers_state=o_state, offers_error=o_error, offers_count=len(o_list),
                          offers_by_name=sum(1 for o in o_list if o["match"] == "nome"),
                          offers_usage=used, offers_limit=settings.shopping_monthly_limit,
                          name_matches=len(name_matches))
    hint = o_hint if product["state"] != "riconosciuto" else None
    return {
        "schema": SCHEMA, "gtin": gtin, "radius_km": radius_km, "position_used": position_used,
        "product": {"state": product["state"], "name": product["name"], "brand": product["brand"],
                    "quantity": product["quantity"], "image_url": product["image_url"], "source": product["source"],
                    "own_brand_chain": own, "corrected_fields": product["corrected_fields"],
                    "name_hint": hint, "name_hint_source": "Google Shopping (non verificato)" if hint else None},
        "online_offers": [_offer_item(o) for o in o_list],
        "online_offers_state": {"state": o_state, "searches_used_month": used,
                                "monthly_limit": settings.shopping_monthly_limit, "error": o_error},
        "catalogs": [_catalog_item(e) for e in certain],
        "catalog_name_matches": [_catalog_item(e) for e in name_matches],
        "stores_with_product_in_catalog": with_info,
        "stores_without_information": without,
        "indexing": {"state": state, "chains_consultable": consultable, "chains_tried": summary["provate"],
                     "chains_confirmed": len(certain)},
        "limits": limits,
    }
