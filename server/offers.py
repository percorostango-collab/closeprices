"""Prezzi online di riferimento (Google Shopping via SerpApi): ripristina ciò che l'app originale dava sempre,
ma dentro la nuova struttura: cache per codice a barre, quota mensile controllata, ogni riga dichiara come è stata trovata.

  match = 'codice' : trovata cercando il codice a barre (e il titolo non contraddice il prodotto)
  match = 'nome'   : trovata cercando per nome; NON verificata col codice: va letta come probabilità."""
import json
import re
from datetime import datetime, timezone

from pvcore.identity import name_match

from .db import now_iso, older_than

SOURCE = "Google Shopping"
MAX_OFFERS = 10


def _clean(text: str, key: str) -> str:
    """Mai la chiave in un messaggio: le eccezioni di requests riportano l'indirizzo completo, chiave compresa."""
    if key:
        text = text.replace(key, "***")
    return re.sub(r"(api_key=)[^&\s'\")]+", r"\1***", text)


def parse_price(raw):
    """'€ 0,89', '0,89 €', 'EUR 1.299,00', '1,299.00' -> float, oppure None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if 0 < raw < 100000 else None
    m = re.search(r"\d[\d.,]*", str(raw))
    if not m:
        return None
    t = m.group(0).rstrip(".,")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) in (1, 2) else t.replace(",", "")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[-1]) == 3):
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if 0 < v < 100000 else None


def normalize(results, product, kind):
    """Dalla risposta grezza alle offerte presentabili: filtro per nome, un'offerta (la più economica) per negozio."""
    best = {}
    for r in results or []:
        title = (r.get("title") or "").strip()
        store = (r.get("source") or r.get("merchant") or "").strip()
        price = parse_price(r.get("extracted_price")) or parse_price(r.get("price"))
        url = r.get("link") or r.get("product_link") or ""
        if not (title and store and price and url.startswith("http")):
            continue
        if product.get("name") or product.get("brand"):
            ok, _ = name_match(product.get("brand") or "", product.get("name") or "", product.get("quantity") or "", title)
            if not ok:
                continue
        cur = best.get(store.lower())
        if cur is None or price < cur["price"]:
            best[store.lower()] = {"store": store, "title": title[:160], "price": price, "currency": "EUR",
                                   "url": url, "match": kind, "source": SOURCE}
    return sorted(best.values(), key=lambda o: o["price"])[:MAX_OFFERS]


def _call(q, settings, fetcher):
    r = fetcher.get(f"{settings.serpapi_base.rstrip('/')}/search.json",
                    params={"engine": "google_shopping", "q": q, "gl": "it", "hl": "it", "api_key": settings.serpapi_key})
    if r.status is None:
        return None, _clean(f"connessione non riuscita ({r.error})", settings.serpapi_key)
    try:
        j = json.loads(r.text)
    except ValueError:
        return None, f"risposta non valida (HTTP {r.status})"
    err = str(j.get("error", "")).lower()
    if r.status == 429 or "limit" in err or "run out of searches" in err:
        return None, "quota SerpApi esaurita"
    if r.status in (401, 403) or "invalid api key" in str(j.get("error", "")).lower():
        return None, "chiave SerpApi rifiutata"
    if r.status != 200 and "hasn't returned any results" not in str(j.get("error", "")):
        return None, _clean(f"HTTP {r.status}: {str(j.get('error', ''))[:120]}", settings.serpapi_key)
    return j.get("shopping_results") or [], None


def search(gtin, product, settings, fetcher) -> dict:
    """Solo rete (nessun accesso al database, quindi gira in parallelo ai cataloghi).
    -> {'state', 'offers', 'searches', 'name_hint', 'error'}"""
    out = {"state": "nessun_risultato", "offers": [], "searches": 0, "name_hint": None, "error": None}
    raw = None
    try:
        raw, err = _call(gtin, settings, fetcher)
        out["searches"] += 1
        if err:
            return dict(out, state="quota_esaurita" if "quota" in err else "errore", error=err)
        if raw:
            out["name_hint"] = (raw[0].get("title") or "").strip()[:120] or None
        offers = normalize(raw, product, "codice")
        if not offers and (product.get("name") or product.get("brand")):
            q = " ".join(x for x in (product.get("brand"), product.get("name"), product.get("quantity")) if x)
            raw2, err = _call(q, settings, fetcher)
            out["searches"] += 1
            if err:
                return dict(out, state="quota_esaurita" if "quota" in err else "errore", error=err)
            offers = normalize(raw2, product, "nome")
        out["offers"] = offers
        out["state"] = "ok" if offers else "nessun_risultato"
    except Exception as e:      # la ricerca dei prezzi non deve mai far fallire la scansione
        out.update(state="errore", error=_clean(f"{type(e).__name__}: {e}", settings.serpapi_key)[:200])
    return out


# ---------------------------------------------------------------- database: cache e quota
def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage(conn) -> int:
    r = conn.execute("SELECT count FROM api_usage WHERE source=? AND month=?", (SOURCE, month_key())).fetchone()
    return r[0] if r else 0


def add_usage(conn, n):
    conn.execute("INSERT INTO api_usage VALUES(?,?,?) ON CONFLICT(source, month) DO UPDATE SET count = count + ?",
                 (SOURCE, month_key(), n, n))


def plan(conn, gtin, settings) -> dict:
    """Cosa fare: usare la cache, non poter cercare, oppure cercare. Lettura sola."""
    if not settings.serpapi_key:
        return {"action": "skip", "state": "non_configurato", "offers": [], "name_hint": None}
    q = conn.execute("SELECT * FROM offer_queries WHERE gtin=? AND source=?", (gtin, SOURCE)).fetchone()
    if q:
        ttl = settings.offers_ttl_days if q["n_offers"] else settings.offers_empty_ttl_days
        if not older_than(q["fetched_at"], ttl):
            rows = [dict(r) for r in conn.execute("SELECT * FROM offers WHERE gtin=? AND source=? ORDER BY price", (gtin, SOURCE))]
            return {"action": "cache", "state": "ok" if rows else "nessun_risultato", "offers": rows,
                    "name_hint": q["name_hint"], "fetched_at": q["fetched_at"]}
    if usage(conn) >= settings.shopping_monthly_limit:
        return {"action": "skip", "state": "quota_esaurita", "offers": [], "name_hint": q["name_hint"] if q else None}
    return {"action": "search", "state": "da_cercare", "offers": [], "name_hint": None}


def save(conn, gtin, result):
    """Salva l'esito di una ricerca (solo se la ricerca è riuscita: un errore momentaneo non si memorizza)."""
    add_usage(conn, result["searches"])
    if result["state"] in ("ok", "nessun_risultato"):
        conn.execute("DELETE FROM offers WHERE gtin=? AND source=?", (gtin, SOURCE))
        for o in result["offers"]:
            conn.execute("INSERT OR REPLACE INTO offers VALUES(?,?,?,?,?,?,?,?,?)",
                         (gtin, o["store"], o["url"], o["title"], o["price"], o["currency"], o["match"], SOURCE, now_iso()))
        conn.execute("INSERT OR REPLACE INTO offer_queries VALUES(?,?,?,?,?)",
                     (gtin, SOURCE, len(result["offers"]), result["name_hint"], now_iso()))
    conn.commit()
