"""Scoperta aperta sul web. OmniRoute (ricerca + lettura + LLM) PROPONE; il nostro codice VERIFICA.

Flusso:  ricerca (per codice e per nome) -> candidati classificati -> ogni pagina letta e controllata:
  - il codice a barre è nella pagina vera (non l'eco di una ricerca)  -> prova (livello 1-2)
  - altrimenti titolo, formato, confezione e varianti coincidono (name_match) -> somiglianza (livello 5)
  - il prezzo si accetta solo se è nei dati strutturati, oppure se l'LLM lo ha indicato E la frase che lo
    contiene esiste davvero, parola per parola, nel testo della pagina (anti-invenzione).
L'LLM non decide mai da solo che un prodotto "c'è", e non inventa indirizzi: li riceve dalla ricerca."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from probe.probe import NOT_PRODUCT, brand_tokens, is_product_url, page_title
from pvcore.gtin import boundary_regex, gtin_variants
from pvcore.identity import name_match
from pvcore.page_check import (Verdict, check_page, distinct_valid_gtins, find_prices, looks_blocked,
                               real_match)
from pvcore.registry import source_for_url

from .db import connect, now_iso, older_than
from .offers import parse_price
from .omniroute import OmniRoute

DENY_HOSTS = ("wikipedia.org", "facebook.com", "instagram.com", "youtube.com", "youtu.be", "pinterest.", "tiktok.com",
              "reddit.com", "twitter.com", "x.com", "linkedin.com", "giallozafferano.it", "cookpad.com", "tripadvisor.",
              "openfoodfacts.org", "openbeautyfacts.org", "google.", "bing.com", "duckduckgo.com")
IN_PROGRESS_STALE_DAYS = 4 / 1440          # una scoperta "in corso" da più di 4 minuti si considera morta


# ---------------------------------------------------------------- candidati
def label_for(url: str) -> str:
    s = source_for_url(url)
    if s:
        return s["canonical"]
    return (urlparse(url).hostname or url).removeprefix("www.")


def rank_candidates(results, gtin, product, limit):
    toks = brand_tokens(product.get("brand") or "", product.get("name") or "") if (product.get("brand") or product.get("name")) else []
    seen, scored = set(), []
    for it in results:
        u = urlparse(it["url"])
        host = (u.hostname or "").lower()
        if not host or any(d in host for d in DENY_HOSTS):
            continue
        key = (host, u.path.rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        blob = f'{it["url"]} {it.get("title", "")} {it.get("snippet", "")}'.lower()
        score = (4 if gtin in it["url"] else 0) + min(3, sum(1 for t in toks if t in blob)) \
            + (1 if source_for_url(it["url"]) else 0) + (1 if is_product_url(it["url"]) else 0) \
            - (3 if NOT_PRODUCT.search(u.path) else 0)
        scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    return [it for sc, it in scored[:limit] if sc > -3]


# ---------------------------------------------------------------- giudizio dell'LLM, con verifica
SYSTEM = ("Sei un verificatore di schede prodotto di negozi online italiani. Rispondi SOLO con un oggetto JSON, "
          "senza altro testo. Non inventare: se un'informazione non c'è, usa null.")


def _excerpt(text: str, limit=6000) -> str:
    lines = [l.strip() for l in re.split(r"[\n\r]+|(?<=\.)\s{2,}", text) if l.strip()]
    head = " ".join(lines)[:2500]
    prices = [l for l in lines if "€" in l or re.search(r"\d+[.,]\d{2}\s*(?:eur|euro)", l, re.I)][:15]
    return (head + "\n" + "\n".join(prices))[:limit]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def verify_price(answer: dict, text: str):
    """Il prezzo indicato dall'LLM vale solo se la frase che lo contiene è nella pagina e contiene quel numero."""
    phrase, value = answer.get("frase_prezzo"), answer.get("prezzo_eur")
    if not phrase or value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if _norm(phrase) not in _norm(text):
        return None
    nums = [parse_price(m) for m in re.findall(r"\d[\d.,]*", phrase)]
    if not any(n is not None and abs(n - value) < 0.005 for n in nums):
        return None
    return value if 0 < value < 10000 else None


def judge(omni, product, gtin, url, title, text):
    prompt = (f"Prodotto cercato: marca={product.get('brand')}; nome={product.get('name')}; formato={product.get('quantity')}; "
              f"codice a barre={gtin}.\nPagina: {url}\nTitolo: {title}\nTesto della pagina (estratto):\n\"\"\"\n{_excerpt(text)}\n\"\"\"\n\n"
              'Rispondi con JSON: {"stesso_prodotto": "si"|"no"|"incerto", "motivo": "una frase", "prezzo_eur": numero|null, '
              '"frase_prezzo": "frase copiata ESATTAMENTE dalla pagina con il prezzo di vendita di UNA confezione '
              '(non il prezzo al kg o al litro)"|null}\nRegole: stesso_prodotto = "si" solo se marca, tipo di prodotto e '
              'formato coincidono; se la confezione è diversa (multipack, 3 kg, cartone) rispondi "no".')
    ans, err = omni.chat_json(SYSTEM, prompt)
    return ans if isinstance(ans, dict) else None


# ---------------------------------------------------------------- verifica di una pagina
def analyse(url, gtin, product, fetcher, robots, omni, llm):
    """-> evidenza (dict) oppure None. [llm] = {'left': n, 'lock': Lock} contatore condiviso delle chiamate."""
    html, text, via = None, None, None
    if robots.allowed(url):
        r = fetcher.get(url)
        if r.status == 200 and not looks_blocked(r.text, 200):
            html, via = r.text, "diretto"
    if html is None:                                   # bloccata o vietata ai nostri server: la legge OmniRoute
        txt, _ = omni.fetch_text(url)
        if txt:
            text, via = txt, "omniroute"
    if html is None and text is None:
        return None
    rx = boundary_regex(gtin_variants(gtin))
    level, price, title = None, None, ""
    if html is not None:
        soup = BeautifulSoup(html, "html.parser")
        title = page_title(soup)
        pr = check_page(html, gtin, 200)
        for t in soup(["script", "style"]):
            t.decompose()
        text = soup.get_text(" ", strip=True)
        if pr.confirmed and not (pr.is_listing and not (pr.verdict == Verdict.CONFIRMED_STRUCTURED and pr.matched_name)):
            level = 1 if pr.verdict == Verdict.CONFIRMED_STRUCTURED else 2
        sp = find_prices(html)
        price = sp[0][0] if sp else None
    else:
        m = re.search(r"^\s*#\s*(.+)$", text, re.M)
        title = (m.group(1) if m else text.strip().split("\n")[0])[:160]
        if real_match(rx, text) and distinct_valid_gtins(text) < 3:
            level = 2
    brand, name, qty = product.get("brand") or "", product.get("name") or "", product.get("quantity") or ""
    similar = level is None and (brand or name) and name_match(brand, name, qty, title)[0]
    if level is None and not similar:
        return None
    ans = None
    if omni.model and (price is None or level is None):
        with llm["lock"]:
            ok = llm["left"] > 0
            llm["left"] -= 1 if ok else 0
        if ok:
            ans = judge(omni, product, gtin, url, title, text)
    if level is None:                                    # solo somiglianza: l'LLM, se c'è, deve confermare
        if ans is not None and ans.get("stesso_prodotto") != "si":
            return None
        level = 5
    if price is None and ans:
        price = verify_price(ans, text)
    return {"chain": label_for(url), "level": level, "url": url, "title": title[:160], "price": price,
            "currency": "EUR" if price else None, "via": via, "llm": ans is not None}


def discover(gtin, product, settings, fetcher, robots, omni) -> dict:
    stats = {"queries": 0, "candidates": 0, "verified": 0, "errors": []}
    queries = [f'"{gtin}"']
    if product.get("brand") or product.get("name"):
        queries.append(" ".join(x for x in (product.get("brand"), product.get("name"), product.get("quantity"), "prezzo") if x))
    results = []
    for q in queries:
        res, err = omni.search(q, max_results=8)
        stats["queries"] += 1
        if err:
            stats["errors"].append(err)
        results += res
    ranked = rank_candidates(results, gtin, product, settings.discovery_max_candidates)
    stats["candidates"] = len(ranked)
    llm = {"left": settings.discovery_llm_calls, "lock": threading.Lock()}
    found = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_safe, analyse, it["url"], gtin, product, fetcher, robots, omni, llm) for it in ranked]
        for f in futs:
            r = f.result()
            if r:
                found.append(r)
    best = {}
    for e in found:                                      # una sola evidenza per sito: la più forte, poi quella con prezzo
        cur = best.get(e["chain"])
        if cur is None or (e["level"], e["price"] is None) < (cur["level"], cur["price"] is None):
            best[e["chain"]] = e
    stats["verified"] = len(best)
    return {"evidence": list(best.values()), "stats": stats}


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


# ---------------------------------------------------------------- database e thread
def run_state(conn, gtin):
    return conn.execute("SELECT * FROM discovery_runs WHERE gtin=?", (gtin,)).fetchone()


def should_run(conn, gtin, settings) -> bool:
    r = run_state(conn, gtin)
    if r is None:
        return True
    if r["state"] == "in_corso":
        return older_than(r["started_at"], IN_PROGRESS_STALE_DAYS)
    return older_than(r["finished_at"] or r["started_at"], settings.discovery_ttl_days)


def mark_started(conn, gtin):
    conn.execute("INSERT OR REPLACE INTO discovery_runs(gtin,state,started_at) VALUES(?,?,?)", (gtin, "in_corso", now_iso()))
    conn.commit()


def save(conn, gtin, res, state="completata", error=None):
    for e in res.get("evidence", []):
        conn.execute("INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?,?,?)",
                     (gtin, e["chain"], e["level"], e["url"], e["title"], e["price"], e["currency"], now_iso()))
    st = res.get("stats", {})
    conn.execute("INSERT OR REPLACE INTO discovery_runs VALUES(?,?,?,?,?,?,?)",
                 (gtin, state, (run_state(conn, gtin) or {"started_at": now_iso()})["started_at"], now_iso(),
                  st.get("candidates", 0), st.get("verified", 0), (error or "; ".join(st.get("errors", [])))[:300] or None))
    conn.commit()


def background(settings, gtin, product, fetcher, robots):
    """Gira in un thread con la SUA connessione: la scansione aspetta un po', poi risponde; il lavoro continua."""
    conn = connect(settings.db_path, settings)
    try:
        res = discover(gtin, product, settings, fetcher, robots, OmniRoute(settings))
        save(conn, gtin, res)
    except Exception as e:
        try:
            save(conn, gtin, {}, state="errore", error=f"{type(e).__name__}: {e}")
        except Exception:
            pass
    finally:
        conn.close()
