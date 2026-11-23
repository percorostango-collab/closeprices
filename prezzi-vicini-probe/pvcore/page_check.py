"""Il codice a barre compare nella pagina? Con quale forza?

Il controllo di lib/services/online_price_service.dart (_verifyPage) era
`body.contains(codice)`. Qui lo si rende più rigoroso:
  - confini di cifra (un numero più lungo che contiene il codice NON conta)
  - dati strutturati (JSON-LD, microdata, meta) = prova forte
  - JSON incorporato (es. __NEXT_DATA__) = prova media
  - testo semplice = prova debole
  - pagina-elenco (più prodotti) segnalata: il codice potrebbe essere di un altro articolo
"""
import json
import re
from dataclasses import dataclass
from enum import Enum

from bs4 import BeautifulSoup

from .gtin import boundary_regex, gtin_variants, normalize_gtin


class Verdict(str, Enum):
    CONFIRMED_STRUCTURED = "confirmed_structured"
    CONFIRMED_JSON = "confirmed_embedded_json"
    CONFIRMED_TEXT = "confirmed_text"
    ABSENT = "absent"
    UNREADABLE = "unreadable"
    BLOCKED = "blocked"


CONFIRMED = {Verdict.CONFIRMED_STRUCTURED, Verdict.CONFIRMED_JSON, Verdict.CONFIRMED_TEXT}


@dataclass
class PageResult:
    verdict: Verdict
    matched_name: str | None = None
    product_count: int = 0       # prodotti dichiarati nei dati strutturati della pagina
    is_listing: bool = False     # più prodotti: l'identità della pagina non è scontata
    detail: str = ""

    @property
    def confirmed(self) -> bool:
        return self.verdict in CONFIRMED


_GTIN_KEYS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14")
_BLOCK_MARKERS = ("cf-chl", "just a moment", "attention required", "captcha",
                  "access denied", "px-captcha", "are you a robot", "verifica che sei umano")
_PRODUCT_TYPES = {"product", "productgroup", "individualproduct", "productmodel"}


def _types(node) -> set:
    t = node.get("@type")
    if isinstance(t, str):
        t = [t]
    return {str(x).split("/")[-1].lower() for x in (t or [])}


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _jsonld_nodes(soup):
    for s in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (s.string or s.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        yield from _walk(data)


_NUM_RE = re.compile(r"(?<!\d)\d{8,14}(?!\d)")


def distinct_valid_gtins(text: str) -> int:
    """Quanti codici a barre diversi (con cifra di controllo valida) compaiono nel testo.
    Se sono tanti, la pagina è un elenco o ha un carosello di prodotti correlati."""
    return len({normalize_gtin(m) for m in _NUM_RE.findall(text)} - {None})


LISTING_THRESHOLD = 3


def looks_blocked(html: str, status: int) -> bool:
    low = (html or "")[:20000].lower()
    if status in (401, 403, 429, 503):
        return True
    return any(m in low for m in _BLOCK_MARKERS) and len(low) < 15000


def check_page(html, gtin: str, status: int = 200) -> PageResult:
    """Verifica che [gtin] compaia nella pagina. Non lancia mai."""
    variants = gtin_variants(gtin)
    rx = boundary_regex(variants)
    if html is None or status is None:
        return PageResult(Verdict.UNREADABLE, detail="nessuna risposta")
    if looks_blocked(html, status):
        return PageResult(Verdict.BLOCKED, detail=f"HTTP {status} o pagina di verifica")
    if status != 200:
        return PageResult(Verdict.UNREADABLE, detail=f"HTTP {status}")

    soup = BeautifulSoup(html, "html.parser")

    # 1) dati strutturati
    products = [n for n in _jsonld_nodes(soup) if _types(n) & _PRODUCT_TYPES]
    count = len(products)
    for n in products:
        for k in _GTIN_KEYS:
            v = n.get(k)
            if v is not None and re.sub(r"\D", "", str(v)) in variants:
                return PageResult(Verdict.CONFIRMED_STRUCTURED, matched_name=n.get("name"),
                                  product_count=count, is_listing=count > 1,
                                  detail=f"JSON-LD {k}")
    for el in soup.find_all(attrs={"itemprop": re.compile(r"^gtin(8|12|13|14)?$", re.I)}):
        v = el.get("content") or el.get_text(strip=True)
        if re.sub(r"\D", "", v or "") in variants:
            return PageResult(Verdict.CONFIRMED_STRUCTURED, product_count=count,
                              is_listing=count > 1, detail="microdata")
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or "").lower()
        if key in ("product:ean", "product:gtin", "og:upc", "og:ean", "gtin", "gtin13", "ean"):
            if re.sub(r"\D", "", m.get("content") or "") in variants:
                return PageResult(Verdict.CONFIRMED_STRUCTURED, product_count=count,
                                  is_listing=count > 1, detail=f"meta {key}")

    # 2) JSON incorporato negli script (non JSON-LD)
    for s in soup.find_all("script"):
        if re.search(r"ld\+json", s.get("type") or "", re.I):
            continue
        body = s.string or s.get_text() or ""
        if body and rx.search(body):
            return PageResult(Verdict.CONFIRMED_JSON, product_count=count,
                              is_listing=count > 1 or distinct_valid_gtins(body) >= LISTING_THRESHOLD,
                              detail="script/JSON incorporato")

    # 3) testo e attributi, senza script e stili
    for t in soup(["script", "style"]):
        t.decompose()
    flat = str(soup)
    if rx.search(flat):
        return PageResult(Verdict.CONFIRMED_TEXT, product_count=count,
                          is_listing=count > 1 or distinct_valid_gtins(flat) >= LISTING_THRESHOLD,
                          detail="testo o attributo della pagina")
    return PageResult(Verdict.ABSENT, product_count=count)
