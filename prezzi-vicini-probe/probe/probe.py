"""Sonda sui cataloghi reali. Risponde a UNA domanda: senza SerpApi, quanti cataloghi
permettono di trovare la scheda di un prodotto e di confermarne il codice a barre?

Regole di buona educazione, tutte attive:
  - si identifica (User-Agent con il repository), rispetta robots.txt
  - al massimo 1 richiesta ogni 1,5 s per sito, poche richieste per sito (~10 a settimana)
  - non fa login, non aggira blocchi: se un sito blocca, lo registra e basta
  - non scarica cataloghi: una ricerca per prodotto e al massimo una scheda
"""
import json
import os
import re
import threading
import time
import urllib.robotparser
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from pvcore.identity import GENERIC, identity_ok, stem
from pvcore.page_check import CONFIRMED, Verdict, check_page, find_gtins, find_prices, looks_blocked
from pvcore.registry import registrable

REPO = os.environ.get("GITHUB_REPOSITORY", "locale")
UA = f"PrezziViciniProbe/0.1 (+https://github.com/{REPO})"


@dataclass
class Resp:
    url: str
    status: int | None = None
    text: str = ""
    headers: dict = field(default_factory=dict)
    error: str | None = None
    ms: int = 0
    raw: bytes = b""


class Fetcher:
    """GET con pausa per sito, limite di dimensione e timeout. Non lancia mai."""

    def __init__(self, min_interval=1.5, timeout=15, max_bytes=2_000_000):
        self.min_interval, self.timeout, self.max_bytes = min_interval, timeout, max_bytes
        self._last, self._locks, self._glock = {}, {}, threading.Lock()
        self.requests_made = 0

    def _host_lock(self, host):
        with self._glock:
            return self._locks.setdefault(host, threading.Lock())

    def get(self, url, params=None, max_bytes=None) -> Resp:
        host = urlparse(url).netloc
        with self._host_lock(host):
            wait = self._last.get(host, 0) + self.min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            t0 = time.time()
            try:
                r = requests.get(url, params=params, timeout=self.timeout, stream=True,
                                 headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
                                          "Accept-Language": "it-IT,it;q=0.9"})
                cap = max_bytes or self.max_bytes
                body = b""
                for chunk in r.iter_content(65536):
                    body += chunk
                    if len(body) >= cap:
                        break
                r.close()
                ctype = r.headers.get("content-type", "")
                text = body.decode(r.encoding or "utf-8", errors="replace") if (
                    "html" in ctype or "xml" in ctype or "json" in ctype or "text" in ctype or not ctype) else ""
                out = Resp(r.url, r.status_code, text, dict(r.headers), None, int((time.time() - t0) * 1000), body)
            except Exception as e:  # rete, TLS, timeout...
                out = Resp(url, None, "", {}, f"{type(e).__name__}: {str(e)[:160]}", int((time.time() - t0) * 1000))
            self._last[host] = time.time()
            self.requests_made += 1
            return out


class Robots:
    def __init__(self, fetcher):
        self.f, self.cache, self.lock = fetcher, {}, threading.RLock()
        self.sitemap_cache = {}

    def load(self, origin):
        with self.lock:
            if origin in self.cache:
                return self.cache[origin]
        r = self.f.get(origin + "/robots.txt", max_bytes=300_000)
        rp = urllib.robotparser.RobotFileParser()
        note = "ok"
        if r.status == 200:
            rp.parse(r.text.splitlines())
        elif r.status in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"]); note = f"HTTP {r.status}: tutto vietato"
        elif r.status is not None and 400 <= r.status < 500:
            rp.parse(["User-agent: *", "Allow: /"]); note = f"HTTP {r.status}: nessun robots.txt"
        else:
            rp.parse(["User-agent: *", "Disallow: /"]); note = f"non leggibile ({r.status or r.error}): per prudenza vietato"
        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text) if r.status == 200 else []
        out = (rp, note, sitemaps, r.status)
        with self.lock:
            self.cache[origin] = out
        return out

    def allowed(self, url):
        u = urlparse(url)
        rp, *_ = self.load(f"{u.scheme}://{u.netloc}")
        return rp.can_fetch(UA, url)


# ---- scoperta della ricerca ----------------------------------------------------------------
SEARCH_NAMES = {"q", "s", "query", "search", "keyword", "keywords", "term", "text", "searchterm",
                "search_query", "ricerca", "cerca", "k", "key", "p"}


def find_search(soup, base_url):
    for form in soup.find_all("form"):
        inputs = form.find_all("input")
        cand = None
        for i in inputs:
            t = (i.get("type") or "text").lower()
            name = (i.get("name") or "").lower()
            hint = ((i.get("placeholder") or "") + (i.get("aria-label") or "") + (i.get("id") or "")).lower()
            if t in ("search", "text") and name and (t == "search" or name in SEARCH_NAMES
                                                    or "cerc" in hint or "search" in hint):
                cand = i
                break
        if not cand:
            continue
        method = (form.get("method") or "get").lower()
        hidden = {i.get("name"): i.get("value", "") for i in inputs
                  if (i.get("type") or "").lower() == "hidden" and i.get("name")}
        action = urljoin(base_url, form.get("action") or base_url)
        return {"url": action, "param": cand.get("name"), "method": method, "hidden": hidden}
    return None


PRODUCT_HINT = re.compile(r"/(prodott[oi]?|product|products|p|articol[oi]|item|detail|scheda|dettaglio)(/|-|$)|-p\d|/\d{5,}", re.I)
NOT_PRODUCT = re.compile(r"/(ricerca|search|cerca|categor\w*|punti-vendita|carte[\w-]*|promozion\w*|volantin\w*|blog|news|contatt\w*|"
                         r"chi-siamo|collezion\w*|concors\w*|reparti|reparto|offerte|negozi|login|account)(/|-|$|\?)", re.I)


def is_product_url(url: str) -> bool:
    path = urlparse(url).path
    return bool(PRODUCT_HINT.search(path)) and not NOT_PRODUCT.search(path)


def brand_tokens(brand, name=""):
    toks = []
    for w in re.split(r"[^a-zà-ú0-9]+", f"{brand}".lower()):
        if len(w) >= 3:
            toks.append(stem(w) if len(w) >= 4 else w)
    return toks or [stem(w) for w in re.split(r"[^a-zà-ú0-9]+", name.lower())
                    if len(w) >= 4 and w not in GENERIC][:1]


def candidate_links(soup, base_url, tokens, limit=2):
    """Solo link che SEMBRANO schede prodotto (percorso da prodotto, non da categoria/ricerca/promo)
    e che nominano la marca. Una pagina qualsiasi non è una scheda."""
    host = registrable(urlparse(base_url).hostname or "")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        u = urlparse(href)
        if u.scheme not in ("http", "https") or registrable(u.hostname or "") != host or href in seen:
            continue
        if not is_product_url(href):
            continue
        text = " ".join([a.get_text(" ", strip=True), a.get("title") or "", a.get("aria-label") or "",
                         unquote(u.path)]).lower()
        if any(t in text for t in tokens):
            seen.add(href)
            out.append(href)
    return out[:limit], len(out)


def page_title(soup):
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    if soup.find("h1"):
        return soup.find("h1").get_text(" ", strip=True)
    return (soup.title.get_text(strip=True) if soup.title else "")[:200]


def is_js_shell(soup):
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    return len(text) < 400 and bool(soup.find(id=re.compile(r"^(root|__next|app|__nuxt)$")))


# ---- sitemap: le schede prodotto espongono un codice a barre? -----------------------------------
def _xml_text(r):
    if not r.raw:
        return r.text or ""
    if r.raw[:2] == b"\x1f\x8b":
        try:
            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(r.raw, 20_000_000).decode("utf-8", "replace")
        except Exception:
            return ""
    return r.text


def _locs(text):
    return re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", text)


def _pick_sub_sitemap(locs):
    def score(u):
        sc = 0
        if re.search(r"prodott|product|item|articol|catalog|shop", u, re.I):
            sc += 2
        if re.search(r"categor|blog|news|page|post|store|punti|vendita|brand|image|video|ricett|recipe", u, re.I):
            sc -= 3
        return sc
    return max(locs, key=score) if locs else None


def probe_sitemap(origin, fetcher, robots, n_pages=3):
    rp, _, sitemaps, _ = robots.load(origin)
    start = sitemaps[0] if sitemaps else origin + "/sitemap.xml"
    with robots.lock:
        if start in robots.sitemap_cache:
            return dict(robots.sitemap_cache[start], condiviso=True)
    out = {"sitemap": start}
    r = fetcher.get(start, max_bytes=3_000_000)
    text = _xml_text(r)
    if r.status != 200 or "<loc" not in text:
        out["esito"] = "sitemap_non_leggibile"
        out["status"] = r.status
    else:
        sub_url, locs = start, _locs(text)
        if "<sitemapindex" in text:
            sub_url = _pick_sub_sitemap(locs)
            sr = fetcher.get(sub_url, max_bytes=3_000_000)
            stext = _xml_text(sr)
            locs = _locs(stext) if sr.status == 200 else []
            out["sotto_sitemap"] = sub_url
        urls = [u for u in locs if is_product_url(u)]
        if not urls and re.search(r"prodott|product|item|articol|catalog", sub_url, re.I):
            urls = [u for u in locs if not u.endswith(".xml")]
        out["url_prodotto_trovati"] = len(urls)
        if not urls:
            out["esito"] = "nessuna_scheda_in_sitemap"
        else:
            pick = sorted({urls[len(urls) // 5], urls[len(urls) // 2], urls[(4 * len(urls)) // 5]})[:n_pages]
            pages = []
            for u in pick:
                if not robots.allowed(u):
                    pages.append({"url": u, "esito": "robots_vieta"})
                    continue
                pr = fetcher.get(u)
                g = find_gtins(pr.text) if pr.status == 200 else {}
                soup = BeautifulSoup(pr.text, "html.parser") if pr.text else None
                pages.append({"url": u, "status": pr.status, "bloccata": looks_blocked(pr.text, pr.status or 0),
                              "gtin": g, "prezzi": find_prices(pr.text) if pr.status == 200 else [],
                              "titolo": (page_title(soup)[:80] if soup else "")})
            out["pagine"] = pages
            ok = [x for x in pages if x.get("status") == 200 and not x.get("bloccata")]
            out["pagine_con_gtin"] = sum(1 for x in ok if x["gtin"])
            out["pagine_lette"] = len(ok)
            out["pagine_con_prezzo"] = sum(1 for x in ok if x["prezzi"])
            out["pagine_con_codice_e_prezzo"] = sum(1 for x in ok if x["gtin"] and x["prezzi"])
            out["esito"] = (("codice_e_prezzo" if out["pagine_con_codice_e_prezzo"] else "solo_codice")
                            if out["pagine_con_gtin"] else
                            ("solo_prezzo" if out["pagine_con_prezzo"] else "ne_codice_ne_prezzo") if ok
                            else "schede_bloccate")
    with robots.lock:
        robots.sitemap_cache[start] = out
    return out


# ---- sonda di un sito ----------------------------------------------------------------------
def _search(site, product, term, fetcher, robots):
    """Una ricerca + (se serve) una scheda. Ritorna il dettaglio, mai lancia."""
    s = site["search"]
    params = dict(s["hidden"]); params[s["param"]] = term
    full = requests.Request("GET", s["url"], params=params).prepare().url
    out = {"term": "codice" if term == product["gtin"] else "nome"}
    if not robots.allowed(full):
        out["outcome"] = "robots_vieta_ricerca"
        return out
    r = fetcher.get(s["url"], params=params)
    out["status"] = r.status
    if r.status != 200:
        out["outcome"] = "bloccato" if looks_blocked(r.text, r.status or 0) else "ricerca_errore"
        out["error"] = r.error
        return out
    res_check = check_page(r.text, product["gtin"], r.status)
    out["codice_nei_risultati"] = res_check.verdict.value
    soup = BeautifulSoup(r.text, "html.parser")
    links, n_strong = candidate_links(soup, r.url, brand_tokens(product["brand"], product.get("name", "")))
    out["candidati"] = len(links)
    if not links:
        out["outcome"] = "nessun_candidato"
        return out
    link = links[0]
    out["scheda_url"] = link
    if not robots.allowed(link):
        out["outcome"] = "robots_vieta_scheda"
        return out
    p = fetcher.get(link)
    out["scheda_status"] = p.status
    pr = check_page(p.text if p.status else None, product["gtin"], p.status or 0)
    out["scheda_esito"] = pr.verdict.value
    out["scheda_elenco"] = pr.is_listing
    psoup = BeautifulSoup(p.text, "html.parser") if p.text else None
    title = page_title(psoup) if psoup else ""
    out["scheda_titolo"] = title[:120]
    if product.get("name"):
        out["identita_titolo_ok"] = identity_ok(product["name"], f'{product["brand"]} {title}')
    out["outcome"] = ("codice_" + pr.verdict.value.replace("confirmed_", "")) if pr.confirmed else \
        {"absent": "scheda_senza_codice", "blocked": "bloccato", "unreadable": "scheda_illeggibile"}[pr.verdict.value]
    return out


CONFIRM_RANK = ["codice_structured", "codice_embedded_json", "codice_text", "scheda_senza_codice",
                "scheda_illeggibile", "nessun_candidato", "robots_vieta_scheda", "robots_vieta_ricerca",
                "ricerca_errore", "bloccato"]


def probe_site(target, products, fetcher, robots, name_fallback=True):
    base = target["base"]
    u = urlparse(base)
    origin = f"{u.scheme}://{u.netloc}"
    res = {"nome": target["name"], "base": base, "in_registro": target.get("in_registro", True)}
    rp, note, sitemaps, rstatus = robots.load(origin)
    res["robots"] = {"status": rstatus, "nota": note, "sitemap_dichiarate": len(sitemaps)}
    if rstatus != 200 and (rstatus is None or rstatus in (202, 401, 403, 429) or rstatus >= 500):
        # robots.txt irraggiungibile o respinto: quasi sempre è il firewall, non un divieto scritto
        res["esito"] = "bloccato_waf_o_robots_illeggibile"
        return res
    if not rp.can_fetch(UA, base):
        res["esito"] = "robots_vieta_tutto"
        return res
    home = fetcher.get(base)
    res["home_status"] = home.status
    if home.status is None:
        res["esito"], res["errore"] = "non_raggiungibile", home.error
        return res
    if looks_blocked(home.text, home.status):
        res["esito"] = "bloccato"
        return res
    if home.status != 200:
        res["esito"] = f"home_http_{home.status}"
        return res
    soup = BeautifulSoup(home.text, "html.parser")
    site_search = find_search(soup, home.url)
    res["js_shell"] = is_js_shell(BeautifulSoup(home.text, "html.parser"))
    try:
        res["sitemap_probe"] = probe_sitemap(origin, fetcher, robots)
    except Exception as e:
        res["sitemap_probe"] = {"esito": "errore_sonda", "errore": f"{type(e).__name__}: {e}"[:160]}
    if not site_search:
        res["esito"] = "js_senza_form_ricerca" if res["js_shell"] else "nessun_form_ricerca"
        return res
    if site_search["method"] != "get":
        res["esito"] = "ricerca_solo_post"
        res["ricerca"] = {"url": site_search["url"], "metodo": site_search["method"]}
        return res
    res["ricerca"] = {"url": site_search["url"], "parametro": site_search["param"]}
    site = {"search": site_search}
    per_product = []
    for p in products:
        d = {"gtin": p["gtin"], "brand": p["brand"], "per_codice": _search(site, p, p["gtin"], fetcher, robots)}
        if name_fallback and d["per_codice"]["outcome"] in ("nessun_candidato", "ricerca_errore"):
            d["per_nome"] = _search(site, p, f'{p["brand"]} {p.get("name", "")}'.strip(), fetcher, robots)
        per_product.append(d)
    res["prodotti"] = per_product
    outcomes = [x["outcome"] for d in per_product for x in (d["per_codice"], d.get("per_nome", {})) if "outcome" in x]
    res["esito"] = min(outcomes, key=lambda o: CONFIRM_RANK.index(o) if o in CONFIRM_RANK else 99) if outcomes else "nessun_esito"
    return res


# ---- Open Food Facts / Open Prices / OSM -------------------------------------------------------
def probe_off(products, fetcher):
    out = []
    for p in products:
        r = fetcher.get(f"https://world.openfoodfacts.org/api/v2/product/{p['gtin']}.json"
                        "?fields=product_name,product_name_it,brands,quantity,stores")
        d = {"gtin": p["gtin"], "status": r.status}
        try:
            j = json.loads(r.text)
            prod = j.get("product") or {}
            d.update(trovato=j.get("status") == 1, nome=prod.get("product_name_it") or prod.get("product_name"),
                     marche=prod.get("brands"), quantita=prod.get("quantity"), negozi=prod.get("stores"))
            if d["trovato"]:
                d["marca_coincide"] = p["brand"].lower().replace("'", "") in (d["marche"] or "").lower().replace("'", "")
        except Exception as e:
            d["errore"] = (r.error or str(e))[:120]
        pr = fetcher.get(f"https://prices.openfoodfacts.org/api/v1/prices?product_code={p['gtin']}&size=1")
        d["open_prices_status"] = pr.status
        try:
            d["open_prices_totale"] = json.loads(pr.text).get("total")
        except Exception:
            d["open_prices_totale"] = None
            d["open_prices_errore"] = (pr.error or pr.text[:100] or "risposta vuota")
        out.append(d)
    return out


CITIES = {"Milano": (45.4642, 9.1900), "Roma": (41.9028, 12.4964), "Napoli": (40.8518, 14.2681)}


OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]


def probe_osm(cities=CITIES, pause=10, endpoints=OVERPASS, retry_pause=8):
    from collections import Counter
    out = {}
    for i, (name, (lat, lon)) in enumerate(cities.items()):
        q = f'[out:json][timeout:60];nwr["shop"="supermarket"](around:5000,{lat},{lon});out tags;'
        d, tried = {}, []
        for attempt in range(2):
            for ep in endpoints:
                try:
                    r = requests.post(ep, data={"data": q}, headers={"User-Agent": UA}, timeout=90)
                    if r.status_code == 200:
                        tags = [e.get("tags", {}) for e in r.json().get("elements", [])]
                        wd = Counter(t["brand:wikidata"] for t in tags if t.get("brand:wikidata"))
                        d = dict(supermercati=len(tags),
                                 con_brand_wikidata=sum(1 for t in tags if t.get("brand:wikidata")),
                                 con_brand=sum(1 for t in tags if t.get("brand")),
                                 solo_nome=sum(1 for t in tags if t.get("name") and not t.get("brand")),
                                 senza_nome=sum(1 for t in tags if not t.get("name")),
                                 top_wikidata=wd.most_common(8), server=ep.split("/")[2])
                        break
                    tried.append(f"{ep.split('/')[2]} HTTP {r.status_code}")
                except Exception as e:
                    tried.append(f"{ep.split('/')[2]} {type(e).__name__}")
            if d:
                break
            time.sleep(retry_pause)
        if not d:
            d["errore"] = "; ".join(tried)[:300]
        out[name] = d
        if i < len(cities) - 1:
            time.sleep(pause)
    return out


# ---- orchestrazione e riepilogo -------------------------------------------------------------------
def targets_from_registry(registry, extra=()):
    seen, out = set(), []
    for s in registry:
        if not s["physical"]:
            continue
        if s["platform"] == "everli":
            base = f"https://it.everli.com/it/spesa/{s['slug']}/"
        elif s["platform"] == "cosicomodo":
            base = f"https://www.cosicomodo.it/{s['slug']}"
        else:
            base = f"https://www.{s['domain']}/"
        if base in seen:
            continue
        seen.add(base)
        out.append({"name": s["name"], "base": base, "kind": s["kind"]})
    out += [dict(e, in_registro=False) for e in extra]
    return out


def run_sites(targets, products, fetcher, workers=8, budget_s=1200):
    robots = Robots(fetcher)
    t0 = time.time()

    def one(t):
        if time.time() - t0 > budget_s:
            return {"nome": t["name"], "base": t["base"], "esito": "saltato_budget_tempo"}
        try:
            r = probe_site(t, products, fetcher, robots)
        except Exception as e:  # la sonda non deve mai fermarsi per un sito
            r = {"nome": t["name"], "base": t["base"], "esito": "errore_sonda", "errore": f"{type(e).__name__}: {e}"[:200]}
        r.setdefault("kind", t.get("kind"))
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, targets))


def render_summary(results: dict) -> str:
    from collections import Counter
    L = [f"# Esito della sonda — {results['generato']}", ""]
    sites = results.get("siti", [])
    if sites:
        c = Counter(s["esito"] for s in sites)
        conf = [s for s in sites if s["esito"].startswith("codice_")]
        L += ["## Cataloghi", "",
              f"Siti provati: **{len(sites)}**. Con il codice a barre confermato nella scheda: **{len(conf)}**.", "",
              "| Esito | Siti |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in c.most_common()]
        L += ["", "| Sito | Esito | Ricerca | Dettaglio |", "|---|---|---|---|"]
        for s in sorted(sites, key=lambda x: (not x["esito"].startswith("codice_"), x["esito"], x["nome"])):
            det = ""
            for d in s.get("prodotti", []):
                x = d["per_codice"]
                det += f'{d["brand"]}: {x.get("outcome")}; '
            L.append(f"| {s['nome']}{'' if s.get('in_registro', True) else ' (fuori registro)'} | {s['esito']} | "
                     f"{(s.get('ricerca') or {}).get('url', '-')} | {det[:140]} |")
    if sites:
        sm = [(x, x.get("sitemap_probe") or {}) for x in sites]
        c2 = Counter(m.get("esito", "sitemap_non_provata") for _, m in sm)
        L += ["", "## Le schede prodotto espongono codice a barre e prezzo? (misura decisiva)", "",
              "Per ogni catena: 3 schede prese dalla sitemap, senza cercare nulla. 'codice' = GTIN valido dichiarato; "
              "'prezzo' = prezzo nei dati strutturati (non dice se dipende dal negozio scelto).", "",
              "| Esito | Catene |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in c2.most_common()]
        L += ["", "| Catena | Esito | Schede lette | Con codice | Con prezzo | Esempio |", "|---|---|---|---|---|---|"]
        for x, m in sorted(sm, key=lambda t: (t[1].get("esito", "z"), t[0]["nome"])):
            ex = ""
            for pg in m.get("pagine", []):
                if pg.get("gtin"):
                    g, w = next(iter(pg["gtin"].items()))
                    pr = pg["prezzi"][0][0] if pg.get("prezzi") else "-"
                    ex = f'{pg["titolo"][:40]} | {g} ({w}) | {pr}'
                    break
            L.append(f"| {x['nome']} | {m.get('esito', '-')} | {m.get('pagine_lette', '-')} | "
                     f"{m.get('pagine_con_gtin', '-')} | {m.get('pagine_con_prezzo', '-')} | {ex} |")
    if results.get("off"):
        L += ["", "## Open Food Facts / Open Prices", "", "| Codice | Trovato | Nome | Marca coincide | Prezzi segnalati | HTTP Open Prices |", "|---|---|---|---|---|---|"]
        for d in results["off"]:
            L.append(f"| {d['gtin']} | {d.get('trovato')} | {d.get('nome')} | {d.get('marca_coincide')} | "
                     f"{d.get('open_prices_totale')} | {d.get('open_prices_status')} {d.get('open_prices_errore', '')} |")
    if results.get("campione_log"):
        L += ["", "## Campione di prodotti", "", "```"] + results["campione_log"] + ["```"]
    if results.get("osm"):
        L += ["", "## OpenStreetMap: supermercati entro 5 km dal centro", "",
              "| Città | Supermercati | con brand:wikidata | con brand | solo nome | Errore |", "|---|---|---|---|---|---|"]
        for city, d in results["osm"].items():
            L.append(f"| {city} | {d.get('supermercati', '-')} | {d.get('con_brand_wikidata', '-')} | "
                     f"{d.get('con_brand', '-')} | {d.get('solo_nome', '-')} | {d.get('errore', '')} |")
    L.append(f"\nRichieste totali: {results.get('richieste')}")
    return "\n".join(L) + "\n"
