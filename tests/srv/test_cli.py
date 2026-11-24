import json

from helpers import G
from probe.probe import Fetcher, Robots
from scenarios import STORES, env
from server import catalogs, cli, products
from server.config import Settings
from server.db import connect


def test_cli_init_load_coverage(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PV_DB", str(tmp_path / "x.db"))
    f = tmp_path / "overpass.json"
    f.write_text(json.dumps({"elements": STORES}), encoding="utf-8")
    cli.main(["init-db"])
    cli.main(["load-stores", "--file", str(f)])
    out = capsys.readouterr().out
    assert '"negozi": 7' in out
    cli.main(["coverage"])
    cov = json.loads(capsys.readouterr().out)
    assert cov["negozi"] == {"totale": 7, "con_catena_riconosciuta": 6}      # "Da Mario" non è di una catena nota
    assert cov["cataloghi"]["catene_consultabili"] == 0


def test_queue_is_processed_with_a_longer_budget():
    with env(delay=1.0, budget=0.3) as (c, ctx):
        r = c.get("/v1/scan", params={"code": G}).json()
        assert r["indexing"]["state"] == "parziale" and r["catalogs"] == []
        s = ctx["settings"]
        conn = connect(s.db_path)
        fetcher = Fetcher(min_interval=0, timeout=5, ua=s.user_agent)
        done = catalogs.process_queue(conn, s, fetcher, Robots(fetcher),
                                      lambda g: products.lookup(conn, g, s, fetcher), limit=5, budget_s=10)
        assert done == 1 and conn.execute("SELECT COUNT(*) FROM index_queue").fetchone()[0] == 0
        assert [e["chain"] for e in catalogs.fresh_evidence(conn, G, 30)] == ["Conad"]
        assert [x["chain"] for x in c.get("/v1/scan", params={"code": G}).json()["catalogs"]] == ["Conad"]
