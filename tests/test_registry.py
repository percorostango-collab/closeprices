import pytest
from pvcore.registry import (duplicate_domains, load_registry, registrable,
                             source_for_url, sources_for_chain)

KINDS = {"ecommerce", "accesso", "cosicomodo", "everli", "specialista", "informativo"}


def test_registry_has_76_entries_and_is_consistent():
    reg = load_registry()
    assert len(reg) == 76
    for s in reg:
        assert s["kind"] in KINDS, s
        assert s["domain"] or (s["platform"] and s["slug"]), s


def test_platform_entries():
    reg = load_registry()
    assert sum(1 for s in reg if s["platform"] == "everli") == 7
    assert sum(1 for s in reg if s["platform"] == "cosicomodo") == 5


def test_registrable():
    assert registrable("www.conad.it") == "conad.it"
    assert registrable("conad.it") == "conad.it"


def test_source_for_url_plain_domain():
    assert source_for_url("https://www.conad.it/prodotti/acqua")["canonical"] == "Conad"
    assert source_for_url("https://spesaonline.esselunga.it/x")["canonical"] == "Esselunga"


def test_source_for_url_platforms():
    assert source_for_url("https://it.everli.com/it/spesa/md/prodotto-x")["canonical"] == "MD"
    assert source_for_url("https://www.cosicomodo.it/mercato/prodotto")["canonical"] == "Mercatò"
    assert source_for_url("https://it.everli.com/it/spesa/altra-insegna/x") is None


def test_unknown_domain_is_none():
    assert source_for_url("https://example.com/x") is None
    assert source_for_url("non-un-url") is None


def test_sources_for_chain_only_physical():
    assert all(s["physical"] for s in sources_for_chain("Coop"))
    assert sources_for_chain("Cicalia") == []         # solo online


def test_known_duplicate_domains_are_documented():
    # Dominio condiviso da due voci: sourceForUrl restituisce la prima e nasconde la seconda.
    # Se cambia, il test avvisa.
    assert set(duplicate_domains()) == {"coop.it", "famila.it"}


@pytest.mark.xfail(strict=True, reason="Lacuna del registro: shop.desparsicilia.it (scheda Despar "
                   "trovata il 23/11/2026) non è tra i domini. Oggi sarebbe scartata come FUORI-DOMINIO.")
def test_regional_despar_shop_resolves_to_despar():
    s = source_for_url("https://shop.desparsicilia.it/spesa-consegna-domicilio/95024/prodotto/x")
    assert s is not None and s["canonical"] == "Despar"
