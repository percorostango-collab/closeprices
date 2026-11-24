"""Scala di fiducia esplicita, GS1 e correzioni degli utenti.

Una prova ha un livello. L'interfaccia mostra di default solo i livelli certi."""
import json
from dataclasses import dataclass
from datetime import date
from enum import Enum, IntEnum

from .gtin import normalize_gtin
from .page_check import PageResult, Verdict
from .registry import DATA


class Level(IntEnum):
    CATALOG_STRUCTURED = 1   # codice nei dati strutturati della scheda del catalogo
    CATALOG_TEXT = 2         # codice nel testo/JSON della scheda (pagina non-elenco)
    OWN_BRAND_PREFIX = 3     # prefisso GS1 della catena (indizio forte, un solo verso)
    USER_CLAIM = 4           # dichiarazione di utenti (es. campo "negozi" di Open Food Facts)
    NAME_SIMILARITY = 5      # nome simile: solo probabilità


class Section(str, Enum):
    CERTAIN = "certo"
    LIKELY = "probabile"
    REPORTED = "segnalato"
    HIDDEN = "nascosto"


def section(level: Level) -> Section:
    if level <= Level.CATALOG_TEXT:
        return Section.CERTAIN
    if level == Level.OWN_BRAND_PREFIX:
        return Section.LIKELY
    if level == Level.USER_CLAIM:
        return Section.REPORTED
    return Section.HIDDEN


@dataclass(frozen=True)
class Evidence:
    chain: str
    level: Level
    source: str
    url: str | None = None
    verified_at: date | None = None


def from_page_result(chain: str, url: str, r: PageResult, today: date | None = None):
    """Trasforma l'esito del controllo-pagina in una prova, o None se non conferma."""
    if not r.confirmed:
        return None
    today = today or date.today()
    if r.verdict == Verdict.CONFIRMED_STRUCTURED:
        # In una pagina-elenco il codice può essere di un altro articolo: serve il nome.
        if r.is_listing and not r.matched_name:
            return Evidence(chain, Level.CATALOG_TEXT, "catalogo-elenco", url, today)
        return Evidence(chain, Level.CATALOG_STRUCTURED, "catalogo", url, today)
    if r.is_listing:
        return None  # codice in testo di una pagina con più prodotti: non basta
    return Evidence(chain, Level.CATALOG_TEXT, "catalogo", url, today)


def best_per_chain(evidences) -> dict:
    """Per ogni catena la prova più forte (livello più basso); a pari livello la più recente."""
    out = {}
    for e in evidences:
        cur = out.get(e.chain)
        if cur is None or (e.level, -(e.verified_at or date.min).toordinal()) < \
                (cur.level, -(cur.verified_at or date.min).toordinal()):
            out[e.chain] = e
    return out


def visible_by_default(evidences) -> list:
    return [e for e in evidences if section(e.level) == Section.CERTAIN]


# ---- GS1 -----------------------------------------------------------------------------
def load_gs1_prefixes() -> dict:
    return json.loads((DATA / "gs1_prefixes.json").read_text(encoding="utf-8"))["prefixes"]


def chain_from_prefix(code: str, prefixes: dict | None = None):
    """Catena che ha registrato il prefisso. Vale in UN verso: un prodotto col prefisso della
    catena è suo; un prodotto senza quel prefisso non dice nulla (molti marchi propri
    portano il prefisso del produttore)."""
    n = normalize_gtin(code)
    if n is None:
        return None
    prefixes = prefixes if prefixes is not None else load_gs1_prefixes()
    for p, chain in prefixes.items():
        if n.startswith(p):
            return chain
    return None


# ---- correzioni condivise ------------------------------------------------------------
@dataclass(frozen=True)
class Correction:
    gtin: str
    field: str       # brand | name | quantity
    value: str
    user_id: str


def effective_fields(base: dict, corrections, min_users: int = 3) -> dict:
    """Una correzione cambia il dato solo se almeno [min_users] utenti DIVERSI propongono lo
    stesso valore. Una sola persona (o lo stesso utente più volte) non riscrive il database."""
    votes = {}
    for c in corrections:
        key = (c.field, " ".join(c.value.lower().split()))
        votes.setdefault(key, {"users": set(), "value": c.value.strip()})["users"].add(c.user_id)
    out = dict(base)
    for (field, _), v in sorted(votes.items(), key=lambda kv: -len(kv[1]["users"])):
        if len(v["users"]) >= min_users and out.get(field) == base.get(field):
            out[field] = v["value"]
    return out
