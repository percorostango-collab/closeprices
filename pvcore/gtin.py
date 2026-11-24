"""Validazione e normalizzazione dei codici a barre (porta di lib/gtin.dart)."""
import re


def checksum_ok(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 2:
        return False
    s = 0
    for i, ch in enumerate(reversed(digits[:-1])):
        s += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - s % 10) % 10 == int(digits[-1])


def normalize_gtin(raw: str):
    """EAN-8, UPC-A, EAN-13, GTIN-14 con cifra di controllo valida.
    UPC-A -> 13 cifre; GTIN-14 con zero iniziale -> 13 cifre; EAN-8 resta a 8."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) not in (8, 12, 13, 14) or not checksum_ok(d):
        return None
    if len(d) == 12:
        return "0" + d
    if len(d) == 14 and d.startswith("0"):
        return d[1:]
    return d


def gtin_variants(code: str) -> set:
    """Scritture equivalenti dello stesso codice (come compare nelle pagine)."""
    n = normalize_gtin(code)
    if n is None:
        raise ValueError(f"codice non valido: {code!r}")
    out = {n}
    if len(n) == 13:
        out.add("0" + n)
        if n.startswith("0"):
            out.add(n[1:])
    elif len(n) == 8:
        out |= {n.rjust(12, "0"), n.rjust(13, "0"), n.rjust(14, "0")}
    return out


def boundary_regex(variants) -> re.Pattern:
    """Il codice deve essere un numero a sé: niente cifre attaccate prima o dopo."""
    alt = "|".join(sorted((re.escape(v) for v in variants), key=len, reverse=True))
    return re.compile(rf"(?<!\d)(?:{alt})(?!\d)")
