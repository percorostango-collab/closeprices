"""Identità del prodotto per testo: porta di online_price_service.dart.

Sono le euristiche che il piano vuole ridurre al minimo (il codice a barre è la chiave
vera), ma finché esistono devono essere testate: ogni caso limite scoperto diventa un test.
"""
import re

GENERIC = {"acqua", "minerale", "naturale", "cioccolato", "cioccolata", "tavoletta",
           "prodotto", "confezione"}

SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ml|cl|lt|litri|litro|l)\b")
LT_PREFIX_RE = re.compile(r"\blt\.?\s*(\d+(?:[.,]\d+)?)")
FRIZ_RE = re.compile(r"frizzante|gassata|effervescente")


def stem(w: str) -> str:
    if len(w) >= 8:
        return w[:6]
    return w[:-1] if (len(w) >= 4 and w[-1] in "aeiouàèéìòù") else w


def _f(x: str):
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def sizes(text: str) -> list:
    """Formati citati nel testo, in g o ml."""
    t = text.lower()
    out = []
    for m in SIZE_RE.finditer(t):
        v = _f(m.group(1))
        if v is None:
            continue
        u = m.group(2)
        if u in ("kg", "l", "lt", "litri", "litro"):
            out.append(v * 1000)
        elif u == "cl":
            out.append(v * 10)
        else:
            out.append(v)
    if re.search(r"(?:^|[^\d.,])\s*litro\b", t):
        out.append(1000.0)
    for m in LT_PREFIX_RE.finditer(t):
        v = _f(m.group(1))
        if v is not None:
            out.append(v * 1000)
    return out


_PACK_PATTERNS = [
    re.compile(r"(?:^|[^\d.,])(\d{1,2})\s*[x×]\s*\d"),
    re.compile(r"(?:^|[\s\d])[x×]\s*(\d{1,2})(?!\d|[.,]\d)"),
    re.compile(r"(\d{1,2})\s*(?:bottiglie|bottiglia|bott|pezzi|pz|confezioni|conf|lattine|buste|vasetti)\b"),
    re.compile(r"confezione da (\d{1,2})"),
]


def pack_count(text: str) -> int:
    t = text.lower()
    for rx in _PACK_PATTERNS:
        m = rx.search(t)
        if m:
            n = int(m.group(1))
            if 1 < n <= 48:
                return n
    return 1


def variant_conflict(name: str, title: str) -> bool:
    n, t = name.lower(), title.lower()
    n_nat, n_fr = "naturale" in n, bool(FRIZ_RE.search(n))
    t_nat, t_fr = "naturale" in t, bool(FRIZ_RE.search(t))
    return (n_nat and t_fr and not t_nat) or (n_fr and t_nat and not t_fr)


def identity_ok(name: str, title: str) -> bool:
    """Il titolo deve essere PROPRIO questo prodotto: stessa percentuale (se citata)
    e ogni parola distintiva del nome presente nel titolo."""
    t = title.lower().replace(",", ".")
    nm = name.lower()
    want = {m.group(1).replace(",", ".") for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", nm)}
    if want:
        got = {m.group(1) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", t)}
        if got and not (want & got):
            return False
    for w in re.split(r"[^a-zà-ú]+", nm):
        if len(w) >= 4 and w not in GENERIC and stem(w) not in t:
            return False
    return True


def same_size(want_text: str, title: str, tol: float = 0.01):
    """True = stesso formato; False = formato diverso; None = non determinabile."""
    want, got = sizes(want_text or ""), sizes(title)
    if not want or not got:
        return None
    return any(abs(g - w) <= w * tol for g in got for w in want)


# ---- confronto per nome, con filtri contro le varianti --------------------------------------------
VARIANT_WORDS = [
    r"plant[- ]?based", r"vegan[oa]?", r"senza glutine", r"gluten[- ]?free", r"senza lattosio", r"lactose[- ]?free",
    r"light", r"zero", r"bio(?:logic[oa])?", r"integral[ei]", r"decaffeinat[oa]", r"mini", r"maxi", r"family",
    r"diet", r"sugar[- ]?free", r"senza zuccher[oi]", r"proteic[oa]", r"protein", r"ricaric[ah]e?", r"refill",
    r"campione", r"sample", r"usato", r"used", r"ricondizionat[oa]", r"kit", r"edizione limitata", r"limited edition",
]


def extra_variant_words(reference: str, title: str) -> list:
    """Parole di variante che il TITOLO ha e il prodotto di riferimento no (es. 'plant based', 'light').
    Se ce ne sono, probabilmente è un altro prodotto della stessa marca."""
    ref, t = reference.lower(), title.lower()
    out = []
    for w in VARIANT_WORDS:
        rx = re.compile(rf"(?<![a-zà-ú]){w}(?![a-zà-ú])")
        if rx.search(t) and not rx.search(ref):
            out.append(rx.search(t).group(0))
    return out


def name_match(brand: str, name: str, quantity: str, title: str):
    """Il titolo di un annuncio/scheda è lo stesso prodotto? Ritorna (True, '') oppure (False, motivo).
    Più severo dell'originale: stessa marca/parole distintive, stesso formato (se noto), stessa confezione,
    nessuna variante in più. NON è una prova: resta una probabilità, e va mostrata come tale."""
    ref = " ".join(x for x in (brand, name, quantity) if x)
    if not identity_ok(name or brand or "", f"{brand} {title}" if brand and brand.lower() not in title.lower() else title):
        return False, "nome diverso"
    if brand and stem(brand.lower().split()[0]) not in title.lower():
        return False, "marca assente nel titolo"
    if quantity and sizes(quantity) and not sizes(title):
        return False, "formato assente nel titolo"          # senza formato non si distingue 0,5 l da 1,5 l
    if same_size(quantity or name or "", title) is False:
        return False, "formato diverso"
    if pack_count(f"{name} {quantity}") != pack_count(title):
        return False, "confezione diversa"
    if variant_conflict(name or "", title):
        return False, "variante in conflitto"
    extra = extra_variant_words(ref, title)
    if extra:
        return False, f"variante in più: {extra[0]}"
    return True, ""
