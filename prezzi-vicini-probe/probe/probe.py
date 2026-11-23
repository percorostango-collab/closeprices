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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from pvcore.identity import GENERIC, identity_ok, stem
from pvcore.page_check import CONFIRMED, Verdict, check_page, looks_blocked
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
                out = Resp(r.url, r.status_code, text, dict(r.headers), None, int((time.time() - t0) * 1000))
            except Exception as e:  # rete, TLS, timeout...
                out = Resp(url, None, "", {}, f"{type(e).__name__}: {str(e)[:160]}", int((time.time() - t0) * 1000))
            self._last[host] = time.time()
            self.requests_made += 1
            return out


class Robots:
    def __init__(self, fetcher):
        self.f, self.cache, self.lock = fetcher, {}, threading.Lock()

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


def brand_tokens(brand, name=""):
    toks = []
    for w in re.split(r"[^a-zà-ú0-9]+", f"{brand}".lower()):
        if len(w) >= 3:
            toks.append(stem(w) if len(w) >= 4 else w)
    return toks or [stem(w) for w in re.split(r"[^a-zà-ú0-9]+", name.lower())
                    if len(w) >= 4 and w not in GENERIC][:1]


def candidate_links(soup, base_url, tokens, limit=2):
    host = registrable(urlparse(base_url).hostname or "")
    seen, strong, weak = set(), [], []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        u = urlparse(href)
        if u.scheme not in ("http", "https") or registrable(u.hostname or "") != host or href in seen:
            continue
        text = " ".join([a.get_text(" ", strip=True), a.get("title") or "", a.get("aria-label") or "",
                         unquote(u.path)]).lower()
        if not any(t in text for t in tokens):
            continue
        seen.add(href)
        (strong if PRODUCT_HINT.search(u.path) else weak).append(href)
    return (strong + weak)[:limit], len(strong)


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
    if sitemaps:
        sm = fetcher.get(sitemaps[0], max_bytes=1_000_000)
        if sm.status == 200:
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm.text)
            res["sitemap"] = {"url": sitemaps[0], "voci": len(locs),
                              "prodotti_nel_nome": sum(1 for x in locs if re.search(r"prodott|product|item|catalog", x, re.I))}
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
        try:
            d["open_prices_totale"] = json.loads(pr.text).get("total")
        except Exception:
            d["open_prices_totale"] = None
        out.append(d)
    return out


CITIES = {"Milano": (45.4642, 9.1900), "Roma": (41.9028, 12.4964), "Napoli": (40.8518, 14.2681)}


def probe_osm(cities=CITIES, pause=20):
    out = {}
    for i, (name, (lat, lon)) in enumerate(cities.items()):
        q = f'[out:json][timeout:60];nwr["shop"="supermarket"](around:5000,{lat},{lon});out tags;'
        d = {}
        try:
            r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q},
                              headers={"User-Agent": UA}, timeout=90)
            if r.status_code != 200:
                d["errore"] = f"HTTP {r.status_code}"
            else:
                els = r.json().get("elements", [])
                tags = [e.get("tags", {}) for e in els]
                from collections import Counter
                wd = Counter(t["brand:wikidata"] for t in tags if t.get("brand:wikidata"))
                d.update(supermercati=len(tags),
                         con_brand_wikidata=sum(1 for t in tags if t.get("brand:wikidata")),
                         con_brand=sum(1 for t in tags if t.get("brand")),
                         solo_nome=sum(1 for t in tags if t.get("name") and not t.get("brand")),
                         senza_nome=sum(1 for t in tags if not t.get("name")),
                         top_wikidata=wd.most_common(8))
        except Exception as e:
            d["errore"] = f"{type(e).__name__}: {str(e)[:120]}"
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
    if results.get("off"):
        L += ["", "## Open Food Facts / Open Prices", "", "| Codice | Trovato | Nome | Marca coincide | Prezzi segnalati |", "|---|---|---|---|---|"]
        for d in results["off"]:
            L.append(f"| {d['gtin']} | {d.get('trovato')} | {d.get('nome')} | {d.get('marca_coincide')} | {d.get('open_prices_totale')} |")
    if results.get("osm"):
        L += ["", "## OpenStreetMap: supermercati entro 5 km dal centro", "",
              "| Città | Supermercati | con brand:wikidata | con brand | solo nome | Errore |", "|---|---|---|---|---|---|"]
        for city, d in results["osm"].items():
            L.append(f"| {city} | {d.get('supermercati', '-')} | {d.get('con_brand_wikidata', '-')} | "
                     f"{d.get('con_brand', '-')} | {d.get('solo_nome', '-')} | {d.get('errore', '')} |")
    L.append(f"\nRichieste totali: {results.get('richieste')}")
    return "\n".join(L) + "\n"
