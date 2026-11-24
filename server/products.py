"""Identità del prodotto: un record per codice a barre. Fonti: Open Food Facts, prefisso GS1, correzioni."""
import json

from probe.probe import Fetcher
from pvcore.evidence import Correction, chain_from_prefix, effective_fields
from pvcore.gtin import normalize_gtin

from .db import now_iso, older_than

FIELDS = "product_name,product_name_it,brands,quantity,image_front_small_url"


def make_fetcher(settings) -> Fetcher:
    return Fetcher(min_interval=settings.request_interval_s, timeout=15, ua=settings.user_agent)


def _fetch_off(gtin, settings, fetcher):
    """-> ('found', dict) | ('missing', None) | ('error', motivo)"""
    r = fetcher.get(f"{settings.off_base}/api/v2/product/{gtin}.json", params={"fields": FIELDS})
    if r.status is None:
        return "error", r.error
    if r.status == 404:
        return "missing", None
    if r.status != 200:
        return "error", f"HTTP {r.status}"
    try:
        j = json.loads(r.text)
    except ValueError:
        return "error", "risposta non valida"
    p = j.get("product") or {}
    name = (p.get("product_name_it") or p.get("product_name") or "").strip()
    if j.get("status") != 1 or not (name or p.get("brands")):
        return "missing", None
    return "found", {"name": name or None, "brand": (p.get("brands") or "").split(",")[0].strip() or None,
                     "quantity": (p.get("quantity") or "").strip() or None, "image_url": p.get("image_front_small_url")}


def _cached(conn, gtin, settings):
    row = conn.execute("SELECT * FROM products WHERE gtin=?", (gtin,)).fetchone()
    if not row:
        return None
    ttl = settings.product_ttl_days if row["found"] else settings.notfound_ttl_days
    return None if older_than(row["fetched_at"], ttl) else row


def corrections_for(conn, gtin):
    return [Correction(r["gtin"], r["field"], r["value"], r["user_id"])
            for r in conn.execute("SELECT * FROM corrections WHERE gtin=?", (gtin,))]


def lookup(conn, gtin, settings, fetcher) -> dict:
    gtin = normalize_gtin(gtin) or gtin
    row = _cached(conn, gtin, settings)
    source_error = None
    if row is None:
        state, data = _fetch_off(gtin, settings, fetcher)
        if state == "found":
            conn.execute("INSERT OR REPLACE INTO products VALUES(?,?,?,?,?,?,?,?)",
                         (gtin, 1, data["name"], data["brand"], data["quantity"], data["image_url"],
                          "Open Food Facts", now_iso()))
        elif state == "missing":
            conn.execute("INSERT OR REPLACE INTO products VALUES(?,?,?,?,?,?,?,?)",
                         (gtin, 0, None, None, None, None, None, now_iso()))
        else:
            source_error = data           # errore momentaneo: NON si memorizza "non trovato"
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE gtin=?", (gtin,)).fetchone()
    base = {"name": row["name"] if row else None, "brand": row["brand"] if row else None,
            "quantity": row["quantity"] if row else None}
    fixed = effective_fields(base, corrections_for(conn, gtin), settings.correction_min_users)
    corrected = [k for k in base if fixed.get(k) != base.get(k)]
    found = bool(row and row["found"]) or bool(fixed.get("name") or fixed.get("brand"))
    source = ("Open Food Facts" if row and row["found"] else None)
    if corrected:
        source = (source + " + correzioni degli utenti") if source else "Correzioni degli utenti"
    return {"gtin": gtin, "state": ("riconosciuto" if found else ("errore_fonte" if source_error else "non_riconosciuto")),
            "name": fixed.get("name"), "brand": fixed.get("brand"), "quantity": fixed.get("quantity"),
            "image_url": row["image_url"] if row else None, "source": source if found else None,
            "own_brand_chain": chain_from_prefix(gtin), "corrected_fields": corrected, "source_error": source_error}


def add_correction(conn, gtin, field, value, user_id) -> dict:
    if normalize_gtin(gtin) is None:
        raise ValueError("codice a barre non valido")
    if field not in ("name", "brand", "quantity"):
        raise ValueError("campo non modificabile")
    value = " ".join((value or "").split())
    if not value or len(value) > 120:
        raise ValueError("valore vuoto o troppo lungo")
    if not user_id or len(user_id) > 80:
        raise ValueError("identificativo utente mancante")
    conn.execute("INSERT INTO corrections(gtin,field,value,user_id,created_at) VALUES(?,?,?,?,?)",
                 (normalize_gtin(gtin), field, value, user_id, now_iso()))
    conn.commit()
    return {"gtin": normalize_gtin(gtin), "field": field, "value": value}
