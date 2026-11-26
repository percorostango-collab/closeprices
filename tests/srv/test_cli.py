import pytest
import json

from helpers import G
from probe.probe import Fetcher, Robots
import scenarios
from scenarios import STORES, env
from server import catalogs, cli, products
from server.config import Settings
from server.db import connect

pytestmark = pytest.mark.usefixtures("db_mode")


def test_cli_init_load_coverage(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PV_DB", str(tmp_path / "x.db"))
    f = tmp_path / "overpass.json"
    f.write_text(json.dumps({"elements": STORES}), encoding="utf-8")
    cli.main(["init-db"])
    cli.main(["load-stores", "--file", str(f)])
    out = capsys.readouterr().out
    assert '"negozi": 7' in out
    # I dati devono finire nel database GIUSTO: su Turso se configurato, altrimenti nel file locale.
    turso = scenarios.MODE.get("turso")
    if turso:
        assert turso.db.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 7
        assert not (tmp_path / "x.db").exists(), "i comandi hanno scritto su un file locale invece che su Turso"
    else:
        assert (tmp_path / "x.db").exists()
    cli.main(["coverage"])
    cov = json.loads(capsys.readouterr().out)
    assert cov["negozi"] == {"totale": 7, "con_catena_riconosciuta": 6}      # "Da Mario" non è di una catena nota
    assert cov["cataloghi"]["catene_consultabili"] == 0


def test_queue_is_processed_with_a_longer_budget():
    with env(delay=1.0, budget=0.3) as (c, ctx):
        r = c.get("/v1/scan", params={"code": G}).json()
        assert r["indexing"]["state"] == "parziale" and r["catalogs"] == []
        s = ctx["settings"]
        conn = connect(s.db_path, s)
        fetcher = Fetcher(min_interval=0, timeout=5, ua=s.user_agent)
        done = catalogs.process_queue(conn, s, fetcher, Robots(fetcher),
                                      lambda g: products.lookup(conn, g, s, fetcher), limit=5, budget_s=10)
        assert done == 1 and conn.execute("SELECT COUNT(*) FROM index_queue").fetchone()[0] == 0
        assert [e["chain"] for e in catalogs.fresh_evidence(conn, G, 30)] == ["Conad"]
        assert [x["chain"] for x in c.get("/v1/scan", params={"code": G}).json()["catalogs"]] == ["Conad"]


def test_cli_diag_shows_state_without_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PV_DB", str(tmp_path / "d.db"))
    cli.main(["diag"])
    j = json.loads(capsys.readouterr().out)
    turso = scenarios.MODE.get("turso")
    assert j["database"] == "ok" and j["database_modo"] == ("turso" if turso else "sqlite-locale")
    assert j["conteggi"]["stores"] == 0
    if turso:
        assert turso.token not in json.dumps(j)


def test_load_stores_only_requested_areas(tmp_path, monkeypatch, capsys):
    from server import stores
    monkeypatch.setenv("PV_DB", str(tmp_path / "b.db"))
    monkeypatch.setattr(stores.time, "sleep", lambda s: None)
    asked = []

    def fake_fetch(query, ua, **kw):
        asked.append(query)
        return {"elements": [STORES[len(asked) % len(STORES)]]}, None
    monkeypatch.setattr(stores, "fetch_tile", fake_fetch)
    cli.main(["load-stores", "--bbox", "45.4,10.5,47.2,12.5;41.4,14.5,43.4,16.5", "--step", "1"])
    txt = capsys.readouterr().out
    out = json.loads(txt[txt.index("{\n"):])                  # prima del risultato ci sono le righe di avanzamento
    assert len(out["aree"]) == 2 and len(asked) == 8          # 4 + 4 tessere da 1 grado, non tutta l'Italia
    assert all("(45." in q or "(46." in q or "(41." in q or "(42." in q for q in asked)


def test_load_stores_rejects_a_malformed_area(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("PV_DB", str(tmp_path / "c.db"))
    with pytest.raises(SystemExit):
        cli.main(["load-stores", "--bbox", "1,2,3"])
