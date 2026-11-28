"""Diagnosi di un prodotto contro i siti REALI (da eseguire su GitHub Actions, dove la rete è aperta).
Per ogni caso "CODICE|indirizzo1,indirizzo2" dice:
  A) per ogni indirizzo: la pagina si apre? contiene il codice? un prezzo? è una pagina costruita con JavaScript?
  B) per ogni catena consultabile del database: cosa succede cercando quel codice (ricerca, candidati, verifica).
Uso:  python tools/diagnose_product.py --casi "8001250120267|https://...,https://...;8025916126592|https://..." """
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from probe.probe import Fetcher, Robots, is_js_shell, page_title  # noqa: E402
from pvcore.gtin import boundary_regex, gtin_variants, normalize_gtin  # noqa: E402
from pvcore.page_check import check_page, find_gtins, find_prices, looks_blocked  # noqa: E402
from server import catalogs, products  # noqa: E402
from server.config import Settings  # noqa: E402
from server.db import connect  # noqa: E402

PRICE_TXT = re.compile(r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)")


def analyse_url(url, gtin, fetcher, robots):
    u = urlparse(url)
    out = {"url": url, "robots_consente": robots.allowed(url)}
    r = fetcher.get(url)
    out.update(status=r.status, errore=r.error, finale=r.url if r.url != url else None)
    if r.status != 200:
        out["esito"] = "non_leggibile"
        return out
    soup = BeautifulSoup(r.text, "html.parser")
    pr = check_page(r.text, gtin, r.status)
    keyed = find_gtins(r.text)
    anywhere = bool(boundary_regex(gtin_variants(gtin)).search(r.text))
    out.update(bloccata=looks_blocked(r.text, r.status), byte=len(r.text), titolo=page_title(soup)[:100],
               js_shell=is_js_shell(BeautifulSoup(r.text, "html.parser")),
               verdetto=pr.verdict.value, codice_ovunque_nel_html=anywhere,
               gtin_dichiarati={g: w for g, w in list(keyed.items())[:5]},
               prezzi_strutturati=[p for p in find_prices(r.text)][:3],
               prezzi_nel_testo=[a or b for a, b in PRICE_TXT.findall(soup.get_text(" "))][:5])
    out["esito"] = ("codice_confermato:" + pr.verdict.value) if pr.confirmed else (
        "bloccata" if out["bloccata"] else ("js" if out["js_shell"] else "senza_codice"))
    return out


def trace_chain(gtin, product, prof, fetcher, robots):
    t = {"catena": prof["chain"], "sito": prof["base"], "ricerca": prof["search_url"], "parametro": prof["search_param"]}
    hidden = json.loads(prof["hidden"] or "{}")
    params = dict(hidden)
    params[prof["search_param"]] = gtin
    full = requests.Request("GET", prof["search_url"], params=params).prepare().url
    t["url_ricerca"] = full
    t["robots_consente"] = robots.allowed(full)
    if not t["robots_consente"]:
        t["esito"] = "robots_vieta"
        return t
    r = fetcher.get(prof["search_url"], params=params)
    t.update(status=r.status, bloccata=looks_blocked(r.text, r.status or 0))
    if r.status != 200:
        t["esito"] = "ricerca_non_riuscita"
        return t
    soup = BeautifulSoup(r.text, "html.parser")
    t["byte"] = len(r.text)
    t["js_shell"] = is_js_shell(BeautifulSoup(r.text, "html.parser"))
    t["codice_nei_risultati"] = bool(boundary_regex(gtin_variants(gtin)).search(r.text))
    tokens = catalogs.brand_tokens(product.get("brand") or "", product.get("name") or "") if product.get("brand") else []
    links = catalogs.product_links(soup, r.url, tokens, limit=5)
    t["candidati"] = []
    for link in links:
        c = {"url": link}
        if not robots.allowed(link):
            c["esito"] = "robots_vieta"
        else:
            p = fetcher.get(link)
            c["status"] = p.status
            pr = check_page(p.text if p.status else None, gtin, p.status or 0)
            c.update(verdetto=pr.verdict.value, titolo=page_title(BeautifulSoup(p.text, "html.parser"))[:90] if p.text else "",
                     prezzi=[x for x in find_prices(p.text)][:2] if p.text else [])
        t["candidati"].append(c)
    t["esito"] = "confermato" if any(c.get("verdetto", "").startswith("confirmed") for c in t["candidati"]) else (
        "nessun_candidato" if not links else "candidati_senza_codice")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--casi", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "diagnosi"))
    a = ap.parse_args()
    s = Settings()
    fetcher = Fetcher(min_interval=1.0, timeout=20, ua=s.user_agent)
    robots = Robots(fetcher)
    conn = connect(s.db_path, s)
    profs = catalogs.usable_profiles(conn)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    for caso in [c for c in a.casi.split(";") if c.strip()]:
        code, _, urls = caso.partition("|")
        gtin = normalize_gtin(code)
        res = {"codice_dato": code.strip(), "gtin": gtin}
        if gtin is None:
            res["errore"] = "codice non valido (cifra di controllo)"
        else:
            prod = products.lookup(conn, gtin, s, fetcher)
            res["prodotto"] = {k: prod.get(k) for k in ("state", "name", "brand", "quantity", "source")}
            res["A_indirizzi_forniti"] = [analyse_url(u.strip(), gtin, fetcher, robots) for u in urls.split(",") if u.strip()]
            res["B_catene_consultabili"] = [trace_chain(gtin, prod, dict(p), fetcher, robots) for p in profs]
            # C) la verifica VERA del servizio (quella di una scansione), rifatta da zero per questo codice
            conn.execute("DELETE FROM attempts WHERE gtin=?", (gtin,))
            conn.execute("DELETE FROM evidence WHERE gtin=?", (gtin,))
            conn.commit()
            res["C_verifica_del_servizio"] = catalogs.index_gtin(conn, gtin, prod, fetcher, robots, budget_s=90.0)
            res["C_conferme_salvate"] = [dict(r) for r in conn.execute(
                "SELECT chain, level, url, title, price FROM evidence WHERE gtin=? ORDER BY level, chain", (gtin,))]
            res["C_esiti_per_catena"] = [dict(r) for r in conn.execute(
                "SELECT chain, outcome FROM attempts WHERE gtin=? ORDER BY outcome, chain", (gtin,))]
        (Path(a.out) / f"{gtin or 'non_valido'}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("scritto", gtin)


if __name__ == "__main__":
    main()
