"""Gli esempi in tests/fixtures/api devono avere la stessa STRUTTURA delle risposte vere del server."""
import json
from pathlib import Path

import pytest
from helpers import G
from scenarios import LAT, LON, env, shape

pytestmark = pytest.mark.usefixtures("db_mode")

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "api"
CASES = {
    "scan_full": (dict(), dict(code=G, lat=LAT, lon=LON)),
    "scan_unknown": (dict(off_products={}), dict(code="8020141800002", lat=LAT, lon=LON)),
    "scan_own_brand": (dict(off_products={}), dict(code="8017596003126", lat=LAT, lon=LON)),
    "scan_no_position": (dict(), dict(code=G)),
    "scan_no_catalogs": (dict(with_profile=False), dict(code=G, lat=LAT, lon=LON)),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_matches_live_shape(name):
    kw, params = CASES[name]
    with env(**kw) as (c, _):
        live = c.get("/v1/scan", params=params).json()
    saved = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    assert shape(saved) == shape(live), "formato cambiato: esegui  python tools/dump_contract.py  e aggiorna l'app"
    assert live["schema"] == 1
