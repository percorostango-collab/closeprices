from datetime import date

from pvcore.evidence import (Correction, Evidence, Level, Section, best_per_chain,
                             chain_from_prefix, effective_fields, from_page_result, section,
                             visible_by_default)
from pvcore.page_check import PageResult, Verdict

D1, D2 = date(2026, 11, 1), date(2026, 11, 20)


def test_sections():
    assert section(Level.CATALOG_STRUCTURED) == Section.CERTAIN
    assert section(Level.CATALOG_TEXT) == Section.CERTAIN
    assert section(Level.OWN_BRAND_PREFIX) == Section.LIKELY
    assert section(Level.USER_CLAIM) == Section.REPORTED
    assert section(Level.NAME_SIMILARITY) == Section.HIDDEN


def test_page_result_to_evidence():
    r = PageResult(Verdict.CONFIRMED_STRUCTURED, matched_name="Uliveto", product_count=1)
    assert from_page_result("Conad", "https://x", r, D1).level == Level.CATALOG_STRUCTURED
    r = PageResult(Verdict.CONFIRMED_TEXT)
    assert from_page_result("Conad", "https://x", r, D1).level == Level.CATALOG_TEXT
    # codice in testo di una pagina-elenco: nessuna prova
    r = PageResult(Verdict.CONFIRMED_TEXT, is_listing=True)
    assert from_page_result("Conad", "https://x", r, D1) is None
    # elenco con dati strutturati: vale solo se il nome dell'articolo con quel codice è noto
    r = PageResult(Verdict.CONFIRMED_STRUCTURED, product_count=3, is_listing=True, matched_name="Uliveto")
    assert from_page_result("Conad", "https://x", r, D1).level == Level.CATALOG_STRUCTURED
    r = PageResult(Verdict.CONFIRMED_STRUCTURED, product_count=3, is_listing=True)
    assert from_page_result("Conad", "https://x", r, D1).level == Level.CATALOG_TEXT
    for v in (Verdict.ABSENT, Verdict.UNREADABLE, Verdict.BLOCKED):
        assert from_page_result("Conad", "https://x", PageResult(v), D1) is None


def test_best_per_chain_prefers_strong_then_recent():
    ev = [Evidence("Coop", Level.USER_CLAIM, "off", None, D2),
          Evidence("Coop", Level.CATALOG_TEXT, "cat", "u1", D1),
          Evidence("Coop", Level.CATALOG_TEXT, "cat", "u2", D2),
          Evidence("Conad", Level.NAME_SIMILARITY, "nome", None, D2)]
    best = best_per_chain(ev)
    assert best["Coop"].url == "u2" and best["Conad"].level == Level.NAME_SIMILARITY


def test_default_view_only_certain():
    ev = [Evidence("A", Level.CATALOG_STRUCTURED, "c"), Evidence("B", Level.OWN_BRAND_PREFIX, "g"),
          Evidence("C", Level.USER_CLAIM, "o"), Evidence("D", Level.NAME_SIMILARITY, "n")]
    assert [e.chain for e in visible_by_default(ev)] == ["A"]


def test_gs1_prefix_one_direction():
    assert chain_from_prefix("8017596003126") == "Eurospin"
    # un prodotto senza il prefisso della catena NON dice che non sia venduto da lei
    assert chain_from_prefix("8008490000021") is None
    assert chain_from_prefix("8017596003127") is None      # codice non valido


def test_single_user_cannot_rewrite_a_product():
    base = {"brand": "Uliveto", "name": "Acqua", "quantity": "1500ml"}
    one = [Correction("8008490000021", "brand", "Pirata", "u1")]
    assert effective_fields(base, one)["brand"] == "Uliveto"
    same_user = [Correction("8008490000021", "brand", "Pirata", "u1")] * 5
    assert effective_fields(base, same_user)["brand"] == "Uliveto"


def test_three_distinct_users_agree():
    base = {"brand": "", "name": "Acqua", "quantity": None}
    cs = [Correction("g", "brand", "Uliveto", u) for u in ("u1", "u2", "u3")]
    assert effective_fields(base, cs)["brand"] == "Uliveto"
    cs2 = [Correction("g", "brand", "Uliveto", "u1"), Correction("g", "brand", "uliveto ", "u2"),
           Correction("g", "brand", "ULIVETO", "u3")]
    assert effective_fields(base, cs2)["brand"] == "Uliveto"
