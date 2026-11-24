import json
import pytest
from pvcore.gtin import boundary_regex, gtin_variants, normalize_gtin
from pvcore.registry import DATA


def test_valid_and_invalid_checksum():
    assert normalize_gtin("8008490000021") == "8008490000021"
    assert normalize_gtin("8008490000022") is None        # cifra di controllo sbagliata
    assert normalize_gtin("12345") is None                # lunghezza non valida
    assert normalize_gtin("") is None and normalize_gtin(None) is None


def test_upc_a_becomes_ean13_and_gtin14_with_zero():
    assert normalize_gtin("036000291452") == "0036000291452"      # UPC-A
    assert normalize_gtin("00036000291452") == "0036000291452"    # GTIN-14 con zero iniziale
    assert normalize_gtin("8008490000021") == "8008490000021"


def test_ean8_stays_8_digits():
    assert normalize_gtin("80134091") == "80134091"


def test_variants_cover_common_writings():
    v = gtin_variants("0036000291452")
    assert {"0036000291452", "036000291452", "00036000291452"} <= v
    assert "80134091" in gtin_variants("80134091")


def test_boundary_rejects_longer_numbers():
    rx = boundary_regex(gtin_variants("8008490000021"))
    assert rx.search("EAN 8008490000021 fine")
    assert rx.search("ean:8008490000021;")
    assert not rx.search("n. 18008490000021")      # cifra attaccata prima
    assert not rx.search("80084900000219")         # cifra attaccata dopo


def test_substring_check_of_the_app_would_be_wrong():
    # Il controllo attuale dell'app è body.contains(codice): questo caso lo mostra.
    text = "riferimento 80084900000219"
    assert "8008490000021" in text                              # l'app direbbe "confermato"
    assert not boundary_regex(gtin_variants("8008490000021")).search(text)


def test_all_golden_codes_are_valid():
    gold = json.loads((DATA / "golden.json").read_text(encoding="utf-8"))["prodotti"]
    bad = [p["gtin"] for p in gold if normalize_gtin(p["gtin"]) is None]
    assert bad == []
