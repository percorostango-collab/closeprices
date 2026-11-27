"""Gli esempi in tests/fixtures/api devono avere la stessa STRUTTURA delle risposte vere del server."""
import json
from pathlib import Path

import pytest
from helpers import G
from scenarios import LAT, LON, env, shape

pytestmark = pytest.mark.usefixtures("db_mode")

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "api"
from contract_cases import CASES  # noqa: E402


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_matches_live_shape(name):
    kw, params = CASES[name]
    with env(**kw) as (c, _):
        live = c.get("/v1/scan", params=params).json()
    saved = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    assert shape(saved) == shape(live), "formato cambiato: esegui  python tools/dump_contract.py  e aggiorna l'app"
    assert live["schema"] == 1
