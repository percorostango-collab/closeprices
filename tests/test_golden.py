import json
from pvcore.evidence import chain_from_prefix
from pvcore.gtin import normalize_gtin
from pvcore.identity import sizes
from pvcore.registry import DATA

GOLD = json.loads((DATA / "golden.json").read_text(encoding="utf-8"))["prodotti"]


def test_unique_codes():
    codes = [p["gtin"] for p in GOLD]
    assert len(codes) == len(set(codes))


def test_quantities_are_parsable():
    for p in GOLD:
        if p["quantity"]:
            assert sizes(p["quantity"]), p


def test_gs1_expectations():
    for p in GOLD:
        want = p.get("gs1_chain")
        assert chain_from_prefix(p["gtin"]) == want, p
    assert any(p.get("gs1_chain") for p in GOLD)


def test_identity_of_golden_names_against_themselves():
    from pvcore.identity import identity_ok
    for p in GOLD:
        if p["name"]:
            assert identity_ok(p["name"], f'{p["brand"]} {p["name"]} {p["quantity"] or ""}'), p
