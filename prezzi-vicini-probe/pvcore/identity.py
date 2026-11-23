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
