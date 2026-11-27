"""Indice dei cataloghi. Due categorie, mai mescolate:
  - prove (livelli 1-2): il codice a barre compare nella scheda. Sono le uniche che sbloccano i negozi vicini.
  - somiglianze (livello 5): nessun codice nella scheda, ma il titolo corrisponde per nome, formato, confezione e
    varianti (pvcore.identity.name_match). Si mostrano sempre come "possibile corrispondenza, non verificata".
Un catalogo non consultabile resta 'non consultabile'."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from probe.probe import (Robots, brand_tokens, candidate_links, find_search, is_js_shell, is_product_url,
                         page_title)
from pvcore.evidence import from_page_result
from pvcore.identity import name_match
from pvcore.page_check import check_page, distinct_valid_gtins, find_prices, looks_blocked
from pvcore.registry import load_registry, registrable

from .db import now_iso, older_than


def registry_targets() -> list:
    seen, out = set(), []
    for s in load_registry():
        if not s["physical"]:
            continue
        if s["platform"] == "everli":
            base = f"https://it.everli.com/it/spesa/{s['slug']}/"
        elif s["platform"] == "cosicomodo":
            base = f"https://www.cosicomodo.it/{s['slug']}"
        else:
            base = f"https://www.{s['domain']}/"
        if base not in seen:
            seen.add(base)
            out.append({"chain": s["canonical"], "name": s["name"], "base": base})
    return out


def physical_chain_count() -> int:
    return len({s["canonical"] for s in load_registry() if s["physical"]})


# ---------------------------------------------------------------- profilo del sito (una volta)
def discover_site(target, fetcher, robots) -> dict:
    """Capisce se il sito si può interrogare in automatico. Non aggira nulla: se blocca, lo si scrive."""
    base = target["base"]
    u = urlparse(base)
    rp, note, _, rstatus = robots.load(f"{u.scheme}://{u.netloc}")
    if rstatus != 200 and (rstatus is None or rstatus in (202, 401, 403, 429) or rstatus >= 500):
        return {"status": "bloccato", "note": f"robots.txt: {note}"}
    if not rp.can_fetch(fetcher.ua, base):
        return {"status": "robots_vieta", "note": "robots.txt vieta l'accesso"}
    home = fetcher.get(base)
    if home.status is None:
        return {"status": "errore", "note": home.error}
    if looks_blocked(home.text, home.status):
        return {"status": "bloccato", "note": f"HTTP {home.status}"}
    if home.status != 200:
        return {"status": "errore", "note": f"HTTP {home.status}"}
    form = find_search(BeautifulSoup(home.text, "html.parser"), home.url)
    if not form:
        js = is_js_shell(BeautifulSoup(home.text, "html.parser"))
        return {"status": "js_senza_ricerca" if js else "senza_ricerca",
                "note": "i prodotti compaiono solo via JavaScript" if js else "nessun modulo di ricerca nella pagina"}
    if form["method"] != "get":
        return {"status": "ricerca_post", "note": "la ricerca usa POST"}
    return {"status": "usabile", "search_url": form["url"], "search_param": form["param"],
            "hidden": json.dumps(form["hidden"]), "note": ""}


def save_profile(conn, target, prof):
    conn.execute("INSERT OR REPLACE INTO site_profiles(chain,base,status,search_url,search_param,hidden,checked_at,note) "
                 "VALUES(?,?,?,?,?,?,?,?)",
                 (target["chain"], target["base"], prof["status"], prof.get("search_url"), prof.get("search_param"),
                  prof.get("hidden"), now_iso(), prof.get("note")))


def discover_all(conn, fetcher, robots, targets=None, workers=8, only_stale_days=None, log=print) -> dict:
    targets = targets if targets is not None else registry_targets()
    if only_stale_days is not None:
        fresh = {(r["chain"], r["base"]) for r in conn.execute("SELECT chain,base,checked_at FROM site_profiles")
                 if not older_than(r["checked_at"], only_stale_days)}
        targets = [t for t in targets if (t["chain"], t["base"]) not in fresh]

    def one(t):
        try:
            return t, discover_site(t, fetcher, robots)
        except Exception as e:
            return t, {"status": "errore", "note": f"{type(e).__name__}: {e}"[:150]}
    counts = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, prof in ex.map(one, targets):
            save_profile(conn, t, prof)
            counts[prof["status"]] = counts.get(prof["status"], 0) + 1
            log(f'{t["name"]}: {prof["status"]}')
    conn.commit()
    return counts


# ---------------------------------------------------------------- verifica di un prodotto in un catalogo
def product_links(soup, base_url, tokens, limit=2):
    if tokens:
        links, _ = candidate_links(soup, base_url, tokens, limit)
        if links:
            return links
    host = registrable(urlparse(base_url).hostname or "")
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if registrable(urlparse(href).hostname or "") == host and is_product_url(href) and href not in out:
            out.append(href)
    return out[:limit]


def _check_by_code(gtin, product, prof, fetcher, robots) -> dict:
    """Cerca il codice nel catalogo e verifica la scheda. Ritorna {'chain','outcome','evidence'}."""
    chain, hidden = prof["chain"], json.loads(prof["hidden"] or "{}")
    params = dict(hidden)
    params[prof["search_param"]] = gtin
    res = {"chain": chain, "base": prof["base"], "outcome": "errore", "evidence": None}
    try:
        if not robots.allowed(requests.Request("GET", prof["search_url"], params=params).prepare().url):
            res["outcome"] = "robots"
            return res
        r = fetcher.get(prof["search_url"], params=params)
        if r.status is None:
            return res
        if looks_blocked(r.text, r.status):
            res["outcome"] = "bloccato"
            return res
        if r.status != 200:
            return res
        soup = BeautifulSoup(r.text, "html.parser")
        tokens = brand_tokens(product.get("brand") or "", product.get("name") or "") if product.get("brand") else []
        links = product_links(soup, r.url, tokens)
        if not links:
            res["outcome"] = "nessun_risultato"
            return res
        res["outcome"] = "scheda_senza_codice"
        for link in links:
            if not robots.allowed(link):
                continue
            p = fetcher.get(link)
            pr = check_page(p.text if p.status else None, gtin, p.status or 0)
            ev = from_page_result(chain, link, pr)
            if ev is None:
                continue
            price = find_prices(p.text)
            title = pr.matched_name or page_title(BeautifulSoup(p.text, "html.parser"))
            res["outcome"] = "confermato"
            res["evidence"] = {"chain": chain, "level": int(ev.level), "url": link, "title": (title or "")[:160],
                               "price": price[0][0] if price else None,
                               "currency": ("EUR" if price and price[0][1] in ("?", "EUR") else (price[0][1] if price else None))}
            return res
    except Exception as e:
        res["outcome"] = "errore"
        res["detail"] = f"{type(e).__name__}: {e}"[:120]
    return res


def _check_by_name(chain, product, prof, fetcher, robots):
    """Seconda possibilità: cerca per nome e accetta una scheda solo se il titolo supera name_match.
    Ritorna un dizionario di evidenza di livello 5, oppure None."""
    brand, name, qty = product.get("brand") or "", product.get("name") or "", product.get("quantity") or ""
    term = " ".join(x for x in (brand, name, qty) if x).strip()
    if not term:
        return None
    params = json.loads(prof["hidden"] or "{}")
    params[prof["search_param"]] = term
    if not robots.allowed(requests.Request("GET", prof["search_url"], params=params).prepare().url):
        return None
    r = fetcher.get(prof["search_url"], params=params)
    if r.status != 200 or looks_blocked(r.text, r.status):
        return None
    tokens = brand_tokens(brand, name) if brand else []
    for link in product_links(BeautifulSoup(r.text, "html.parser"), r.url, tokens, limit=3):
        if not robots.allowed(link):
            continue
        p = fetcher.get(link)
        if p.status != 200 or looks_blocked(p.text, p.status) or distinct_valid_gtins(p.text) >= 3:
            continue                                   # pagina non leggibile, o un elenco di prodotti
        title = page_title(BeautifulSoup(p.text, "html.parser"))
        ok, _ = name_match(brand, name, qty, title)
        if ok:
            price = find_prices(p.text)
            return {"chain": chain, "level": 5, "url": link, "title": title[:160],
                    "price": price[0][0] if price else None,
                    "currency": ("EUR" if price and price[0][1] in ("?", "EUR") else (price[0][1] if price else None))}
    return None


def check_chain(gtin, product, prof, fetcher, robots) -> dict:
    """Prima il codice (prova); se non conferma, il nome (somiglianza, dichiarata come tale)."""
    res = _check_by_code(gtin, product, prof, fetcher, robots)
    if res["outcome"] in ("nessun_risultato", "scheda_senza_codice") and (product.get("brand") or product.get("name")):
        try:
            ne = _check_by_name(prof["chain"], product, prof, fetcher, robots)
        except Exception:
            ne = None
        if ne:
            res["name_evidence"], res["outcome"] = ne, "somiglianza_nome"
    return res


def needs_index(conn, gtin, ttl_days) -> bool:
    last = conn.execute("SELECT MAX(tried_at) FROM attempts WHERE gtin=?", (gtin,)).fetchone()[0]
    return last is None or older_than(last, ttl_days)


def usable_profiles(conn) -> list:
    return list(conn.execute("SELECT * FROM site_profiles WHERE status='usabile'"))


def index_gtin(conn, gtin, product, fetcher, robots, budget_s=8.0, workers=8) -> dict:
    """Prova il codice in tutti i cataloghi consultabili, entro il tempo disponibile."""
    profs = usable_profiles(conn)
    out = {"consultabili": len({p["chain"] for p in profs}), "provate": 0, "confermate": 0, "somiglianze": 0, "incomplete": 0}
    if not profs:
        return out
    ex = ThreadPoolExecutor(max_workers=workers)
    futs = [ex.submit(check_chain, gtin, product, dict(p), fetcher, robots) for p in profs]
    done, pending = wait(futs, timeout=budget_s)
    ex.shutdown(wait=False, cancel_futures=True)
    by_chain = {}
    for f in done:
        r = f.result()
        prev = by_chain.get(r["chain"])
        rank = {"confermato": 2, "somiglianza_nome": 1}
        if prev is None or rank.get(r["outcome"], 0) > rank.get(prev["outcome"], 0):
            by_chain[r["chain"]] = r
    for chain, r in by_chain.items():
        conn.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?,?)", (gtin, chain, r["outcome"], now_iso()))
        if r["evidence"]:
            e = r["evidence"]
            conn.execute("INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?,?,?)",
                         (gtin, e["chain"], e["level"], e["url"], e["title"], e["price"], e["currency"], now_iso()))
        if r.get("name_evidence"):
            e = r["name_evidence"]
            conn.execute("INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?,?,?)",
                         (gtin, e["chain"], e["level"], e["url"], e["title"], e["price"], e["currency"], now_iso()))
    conn.commit()
    out["provate"] = len(by_chain)
    out["somiglianze"] = sum(1 for r in by_chain.values() if r["outcome"] == "somiglianza_nome")
    out["confermate"] = sum(1 for r in by_chain.values() if r["outcome"] == "confermato")
    out["incomplete"] = len(pending)
    return out


def fresh_evidence(conn, gtin, ttl_days) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM evidence WHERE gtin=? ORDER BY level, chain", (gtin,))
            if not older_than(r["verified_at"], ttl_days)]


def process_queue(conn, settings, fetcher, robots, lookup, limit=5, budget_s=60.0) -> int:
    n = 0
    for row in list(conn.execute("SELECT gtin FROM index_queue ORDER BY requested_at LIMIT ?", (limit,))):
        gtin = row["gtin"]
        index_gtin(conn, gtin, lookup(gtin), fetcher, robots, budget_s=budget_s)
        conn.execute("DELETE FROM index_queue WHERE gtin=?", (gtin,))
        conn.commit()
        n += 1
    return n


def coverage(conn) -> dict:
    status = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(DISTINCT chain) FROM site_profiles GROUP BY status")}
    usable = conn.execute("SELECT COUNT(DISTINCT chain) FROM site_profiles WHERE status='usabile'").fetchone()[0]
    return {"catene_con_negozi_fisici": physical_chain_count(), "catene_consultabili": usable,
            "stato_siti": status,
            "prodotti_con_conferma": conn.execute("SELECT COUNT(DISTINCT gtin) FROM evidence").fetchone()[0],
            "prodotti_provati": conn.execute("SELECT COUNT(DISTINCT gtin) FROM attempts").fetchone()[0]}
