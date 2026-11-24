"""Riconoscimento delle catene dai negozi di OpenStreetMap (porta di lib/chains.dart)."""
import re
from dataclasses import dataclass

from pvcore.registry import load_registry

FOOD = "supermarket|convenience"


@dataclass(frozen=True)
class ChainDef:
    canonical: str
    shops: str
    brands: tuple
    name_re: str

    def matches(self, brand: str | None, name: str | None) -> bool:
        if brand and brand.strip().lower() in {b.lower() for b in self.brands}:
            return True
        return bool(name and re.search(self.name_re, name, re.I))


def C(canonical, shops, brands, name_re):
    return ChainDef(canonical, shops, tuple(brands), name_re)


KNOWN = [
    C("Coop", FOOD, ["Coop", "Coop Alleanza 3.0", "Unicoop Tirreno", "Unicoop Firenze", "Unicoop Etruria", "Coop Lombardia",
                     "Coop Liguria", "Coop Centro Italia", "Nova Coop", "Coop Reno", "Coop Estense", "Coop Adriatica", "Ipercoop"],
      r"Coop|Ipercoop|Unicoop"),
    C("Conad", FOOD, ["Conad", "Conad City", "Conad Superstore", "Conad Margherita", "Spazio Conad"], r"Conad"),
    C("Esselunga", FOOD, ["Esselunga"], r"Esselunga"),
    C("Carrefour", FOOD, ["Carrefour", "Carrefour Market", "Carrefour Express", "Carrefour Iper"], r"Carrefour"),
    C("Lidl", FOOD, ["Lidl"], r"Lidl"),
    C("Aldi", FOOD, ["Aldi"], r"^Aldi"),
    C("Eurospin", FOOD, ["Eurospin"], r"Eurospin"),
    C("MD", FOOD, ["MD", "MD Discount"], r"^MD( |$)"),
    C("Pam", FOOD, ["Pam", "Pam Panorama", "Panorama", "Pam Local"], r"^(Pam|Panorama)"),
    C("Todis", FOOD, ["Todis"], r"Todis"),
    C("Penny", FOOD, ["Penny", "Penny Market"], r"Penny"),
    C("Despar", FOOD, ["Despar", "Eurospar", "Interspar", "Despar Express"], r"Despar|Eurospar|Interspar"),
    C("Elite", FOOD, ["Elite", "Super Elite"], r"^(Super )?Elite"),
    C("Tigros", FOOD, ["Tigros"], r"Tigros"),
    C("Bennet", FOOD, ["Bennet"], r"Bennet"),
    C("Famila", FOOD, ["Famila"], r"Famila"),
    C("Iperal", FOOD, ["Iperal"], r"Iperal"),
    C("Tuttigiorni", FOOD, ["Tuttigiorni", "Tuttogiorni"], r"Tuttigiorni|Tuttogiorni"),
    C("Decò", FOOD, ["Decò", "Deco", "Decò Supermercati"], r"Dec[oò]"),
    C("U2 Supermercato", FOOD, ["U2 Supermercato", "U2"], r"^U2( |$)"),
    C("Crai", FOOD, ["Crai"], r"Crai"),
]

_synth = None


def _synthetic():
    """Insegne del registro cataloghi non elencate sopra: nome all'inizio del nome del negozio."""
    global _synth
    if _synth is None:
        known = {c.canonical.lower() for c in KNOWN}
        names = sorted({s["canonical"] for s in load_registry() if s["physical"]} , key=len, reverse=True)
        _synth = [ChainDef(n, FOOD, (n,), r"^(%s)( |$)" % re.sub(r"[^A-Za-z0-9à-úÀ-Ú ]", ".", n))
                  for n in names if n.lower() not in known and len(n) >= 3]
    return _synth


def classify(brand: str | None, name: str | None):
    """Nome canonico della catena, oppure None."""
    for c in KNOWN:
        if c.matches(brand, name):
            return c.canonical
    for c in _synthetic():
        if c.matches(brand, name):
            return c.canonical
    return None


def all_shop_values() -> str:
    return FOOD
