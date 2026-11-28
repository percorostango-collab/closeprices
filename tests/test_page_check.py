from conftest import page
from pvcore.page_check import Verdict, check_page

G = "8008490000021"


def test_jsonld_product():
    r = check_page(page("product_jsonld.html"), G)
    assert r.verdict == Verdict.CONFIRMED_STRUCTURED
    assert "Uliveto" in r.matched_name and not r.is_listing


def test_jsonld_graph_with_numeric_gtin_and_type_list():
    assert check_page(page("product_graph_jsonld.html"), G).verdict == Verdict.CONFIRMED_STRUCTURED


def test_jsonld_listing_is_flagged():
    r = check_page(page("listing_jsonld.html"), G)
    assert r.verdict == Verdict.CONFIRMED_STRUCTURED
    assert r.is_listing and r.product_count == 3
    assert "Uliveto" in r.matched_name        # il nome dell'articolo che ha quel codice


def test_microdata_and_meta():
    assert check_page(page("product_microdata.html"), G).verdict == Verdict.CONFIRMED_STRUCTURED
    assert check_page(page("product_meta.html"), G).verdict == Verdict.CONFIRMED_STRUCTURED


def test_embedded_json():
    assert check_page(page("product_nextdata.html"), G).verdict == Verdict.CONFIRMED_JSON


def test_text_only_is_weaker():
    r = check_page(page("product_text_only.html"), G)
    assert r.verdict == Verdict.CONFIRMED_TEXT and not r.is_listing


def test_longer_numbers_do_not_confirm():
    assert check_page(page("longer_number.html"), G).verdict == Verdict.ABSENT


def test_absent_and_js_shell():
    assert check_page(page("no_code.html"), G).verdict == Verdict.ABSENT
    assert check_page(page("js_shell.html"), G).verdict == Verdict.ABSENT


def test_blocked_and_unreadable():
    assert check_page(page("blocked.html"), G).verdict == Verdict.BLOCKED
    assert check_page("<html></html>", G, status=403).verdict == Verdict.BLOCKED
    assert check_page("<html></html>", G, status=404).verdict == Verdict.UNREADABLE
    assert check_page(None, G).verdict == Verdict.UNREADABLE


def test_carousel_of_related_products_is_a_listing():
    # il codice cercato è di un ALTRO prodotto, citato in "Altri prodotti"
    r = check_page(page("carousel_text.html"), G)
    assert r.verdict == Verdict.CONFIRMED_TEXT and r.is_listing


def test_upc_variant_is_found():
    html = "<html><body><p>UPC 036000291452</p></body></html>"
    assert check_page(html, "0036000291452").verdict == Verdict.CONFIRMED_TEXT


def test_never_raises_on_garbage():
    for h in ["", "<<<>>>", "<script type='application/ld+json'>{rotto</script>"]:
        assert check_page(h, G).verdict in (Verdict.ABSENT, Verdict.UNREADABLE)


# ---- eco della ricerca: i casi che davano falsi positivi sui siti reali (Dem, Migross, Si con Te, SpesaSicura) ----
import pytest  # noqa: E402

CODE = "8001250120267"
ECHOES = {
    "casella di ricerca": f'<form><input type="search" value="{CODE}"></form><p>Nessun risultato</p>',
    "titolo": f'<html><head><title>Risultati per {CODE}</title></head><body>Niente</body></html>',
    "link ?s=": f'<a href="/?s={CODE}">Vedi tutti</a>',
    "link dgwt": f'<a href="/?post_type=product&dgwt_wcas=1&s={CODE}">x</a>',
    "script query": f'<script>window.S={{"query":"{CODE}","n":0}}</script>',
    "script search=": f'<script>var u="search={CODE}";</script>',
    "returnurl codificato": f'<a href="/login?returnurl=https%3A%2F%2Fx.it%2F%3Fs%3D{CODE}">Accedi</a>',
    "canonical ?q=": f'<head><link rel="canonical" href="https://x.it/cerca?q={CODE}"></head><body>x</body>',
}
GENUINE = {
    "percorso prodotto in JSON (Carrefour)": (f'<script>var p={{"url":"https://www.carrefour.it/p/de-cecco/{CODE}.html"}}</script>', "confirmed_embedded_json"),
    "testo EAN": (f"<p>Codice EAN: {CODE}</p>", "confirmed_text"),
    "attributo dati": (f'<div data-product-ean="{CODE}">Prodotto</div>', "confirmed_text"),
    "JSON-LD": ('<script type="application/ld+json">{"@type":"Product","gtin13":"%s"}</script>' % CODE, "confirmed_structured"),
}


@pytest.mark.parametrize("name", sorted(ECHOES))
def test_search_echo_is_never_a_proof(name):
    from pvcore.page_check import Verdict, check_page
    assert check_page(f"<html><body>{ECHOES[name]}</body></html>", CODE).verdict == Verdict.ABSENT


@pytest.mark.parametrize("name", sorted(GENUINE))
def test_genuine_product_codes_still_confirm(name):
    from pvcore.page_check import check_page
    html, expected = GENUINE[name]
    assert check_page(f"<html><body>{html}</body></html>", CODE).verdict.value == expected
