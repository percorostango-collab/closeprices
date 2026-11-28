import pytest
from pvcore.identity import (identity_ok, pack_count, same_size, sizes, stem,
                             variant_conflict)


def test_stem():
    assert stem("caramello") == "carame"      # 8+ lettere: prime 6
    assert stem("noce") == "noc" and stem("noci") == "noc"
    assert stem("uliveto") == "ulivet"


def test_sizes_units():
    assert sizes("Acqua 1,5 l") == [1500]
    assert sizes("Acqua 1500ml") == [1500]
    assert sizes("Birra 33 cl") == [330]
    assert sizes("Pasta 500 gr") == [500]
    assert sizes("Pasta 0,5 kg") == [500]
    assert sizes("Acqua lt. 1,5") == [1500]
    assert sizes("acqua litro x 12") == [1000]
    assert sizes("Compresse 1000 mg") == []          # i milligrammi non sono un formato


def test_pack_count():
    assert pack_count("Acqua 6 x 1,5 l") == 6
    assert pack_count("Acqua 1,5 l x 12") == 12
    assert pack_count("Confezione da 6") == 6
    assert pack_count("12 lattine 33cl") == 12
    assert pack_count("Acqua 1,5 l") == 1
    assert pack_count("Maxi 500 g") == 1             # la x dentro una parola non conta


def test_same_size():
    assert same_size("1500ml", "Uliveto 1,5 L") is True
    assert same_size("1500ml", "Uliveto 0,5 L") is False
    assert same_size("1500ml", "Uliveto") is None
    assert same_size(None, "Uliveto 1,5 L") is None


def test_variant_conflict():
    assert variant_conflict("Acqua naturale", "Acqua frizzante 1,5 L")
    assert variant_conflict("Acqua frizzante", "Acqua naturale 1,5 L")
    assert not variant_conflict("Acqua naturale", "Acqua naturale 1,5 L")
    # caso Uliveto: Open Food Facts dice "naturale", il prodotto è effervescente NATURALE
    assert not variant_conflict("Acqua Minerale Naturale Uliveto",
                                "Uliveto acqua effervescente naturale 1,5 L")


def test_identity_percent():
    assert identity_ok("Cioccolato fondente 70% Lindt", "Lindt fondente 70% 100 g")
    assert not identity_ok("Cioccolato fondente 70% Lindt", "Lindt fondente 85% 100 g")
    assert identity_ok("Cioccolato fondente 70% Lindt", "Lindt fondente 100 g")   # percentuale non citata


def test_identity_distinctive_words():
    assert identity_ok("Tavoletta caramello Lindt", "Lindt Caramel 100 g")
    assert not identity_ok("Tavoletta caramello Lindt", "Lindt Nocciole 100 g")
    assert identity_ok("Acqua Minerale Naturale Uliveto", "Uliveto acqua effervescente naturale 1,5 L")
    assert not identity_ok("Acqua Minerale Naturale Uliveto", "Acqua Sant'Anna 1,5 L")


@pytest.mark.parametrize("text,expected", [
    ("Zucchero 1000 grammi", [1000]),
    ("Pasta 1 kilo", [1000]),
    ("Succo 200 millilitri", [200]),
])
@pytest.mark.xfail(strict=True, reason="Limite noto di _sizeRe nell'app: unità scritte per esteso "
                   "non sono riconosciute, quindi il controllo del formato viene saltato.")
def test_spelled_out_units(text, expected):
    assert sizes(text) == expected


# ---- name_match: la corrispondenza per nome, con i casi che in passato davano falsi risultati ----
from pvcore.identity import extra_variant_words, name_match  # noqa: E402

UL = ("Uliveto", "Acqua minerale naturale", "1,5 l")


@pytest.mark.parametrize("title,ok", [
    ("Acqua Uliveto 1,5 L", True),
    ("Uliveto Acqua Minerale Naturale 1.5 L", True),
    ("ULIVETO acqua effervescente naturale 1500 ml", True),
    ("Acqua Uliveto 0,5 L", False),                    # formato diverso
    ("Acqua Uliveto 1,5 L x 6", False),                # confezione diversa
    ("Acqua Sant'Anna 1,5 L", False),                  # altra marca
    ("Acqua Uliveto Zero 1,5 L", False),               # variante in più
    ("Acqua Uliveto frizzante 1,5 L", False),          # variante in conflitto (naturale vs frizzante)
    ("Uliveto - altra cosa", False),                   # nessun formato nel titolo: non si distingue il prodotto
    ("Offerte Uliveto", False),
])
def test_name_match_water(title, ok):
    assert name_match(*UL, title)[0] is ok


def test_plant_based_nutella_is_not_nutella():
    assert name_match("Nutella", "Nutella", "350 g", "Nutella 350 g")[0]
    ok, why = name_match("Nutella", "Nutella", "350 g", "Nutella Plant-Based 350 g")
    assert not ok and "plant" in why
    assert not name_match("Nutella", "Nutella", "350 g", "Nutella Biscuits 193 g")[0]          # altro formato


def test_variant_words_only_count_when_the_reference_lacks_them():
    assert extra_variant_words("Coca-Cola Zero 330 ml", "Coca Cola Zero lattina 330 ml") == []
    assert extra_variant_words("Coca-Cola 330 ml", "Coca Cola Zero 330 ml") == ["zero"]
    assert extra_variant_words("Yogurt greco", "Yogurt greco bio") == ["bio"]
    assert extra_variant_words("Mini Babybel", "Babybel mini") == []
    assert extra_variant_words("Pasta Barilla", "Pasta Barilla biologica")[0].startswith("bio")


def test_name_match_with_unknown_quantity_still_checks_the_rest():
    assert name_match("Barilla", "Spaghetti n.5", "", "Barilla Spaghetti n.5 500 g")[0]
    assert not name_match("Barilla", "Spaghetti n.5", "", "Barilla Penne Rigate 500 g")[0]
