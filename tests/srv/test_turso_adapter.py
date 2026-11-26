"""Il client Turso del servizio, provato contro un finto Turso che parla lo stesso protocollo HTTP."""
import pytest
from fake_turso import FakeTurso
from fastapi.testclient import TestClient
from server import db as dbmod
from server.app import create_app
from server.config import Settings
from server.db import DatabaseError, Row, TursoConnection, connect


@pytest.fixture
def ft():
    f = FakeTurso()
    yield f
    f.close()


def conn_to(ft, **kw):
    return TursoConnection(ft.url, kw.pop("token", ft.token), **kw)


def test_types_roundtrip_and_row_access(ft):
    c = conn_to(ft)
    c.execute("CREATE TABLE t(a INTEGER, b REAL, c TEXT, d BLOB, e TEXT)")
    c.execute("INSERT INTO t VALUES(?,?,?,?,?)", (7, 1.5, "àé€", b"\x00\xff", None))
    c.execute("INSERT INTO t VALUES(?,?,?,?,?)", (True, 0.0, "", b"", None))
    rows = c.execute("SELECT * FROM t ORDER BY a").fetchall()
    r = rows[1]
    assert isinstance(r, Row) and (r["a"], r["b"], r["c"], r["d"], r["e"]) == (7, 1.5, "àé€", b"\x00\xff", None)
    assert r[0] == 7 and r.keys() == ["a", "b", "c", "d", "e"] and len(r) == 5
    assert dict(r) == {"a": 7, "b": 1.5, "c": "àé€", "d": b"\x00\xff", "e": None}
    assert rows[0]["a"] == 1 and isinstance(rows[0]["a"], int)        # bool -> intero
    assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    assert c.execute("SELECT * FROM t WHERE a=999").fetchone() is None
    with pytest.raises(IndexError):
        r["inesistente"]


def test_named_parameters_become_positional(ft):
    c = conn_to(ft)
    c.execute("CREATE TABLE t(x TEXT, y TEXT)")
    c.execute("INSERT INTO t VALUES(:a, :b)", {"a": "uno", "b": "due"})
    c.execute("INSERT INTO t VALUES(:a, :a)", {"a": "ripetuto"})
    assert [tuple(r) for r in c.execute("SELECT * FROM t ORDER BY x")] == [("ripetuto", "ripetuto"), ("uno", "due")]
    # i due punti dentro un testo non sono parametri
    assert c.execute("SELECT '12:30' AS ora, 'a:b' AS k").fetchone()["ora"] == "12:30"
    assert "?" in ft.sql_log[1] and ":a" not in ft.sql_log[1]          # al server arrivano solo '?'


def test_cursor_attributes(ft):
    c = conn_to(ft)
    c.executescript("CREATE TABLE corr(id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);")
    cur = c.execute("INSERT INTO corr(v) VALUES(?)", ("x",))
    assert cur.lastrowid == 1 and cur.rowcount == 1
    assert c.execute("UPDATE corr SET v='y'").rowcount == 1
    cur = c.execute("SELECT * FROM corr")
    assert cur.fetchone()["v"] == "y" and cur.fetchone() is None and cur.fetchall() == []


def test_executemany_sends_groups_not_one_request_per_row(ft):
    c = conn_to(ft)
    c.execute("CREATE TABLE t(n INTEGER)")
    before = ft.http_requests
    c.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(450)])
    assert ft.http_requests - before == 3                             # 200 + 200 + 50
    assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 450
    n = ft.http_requests
    c.executemany("INSERT INTO t VALUES(?)", [])                       # vuoto: nessuna richiesta
    assert ft.http_requests == n


def test_executescript_splits_statements(ft):
    c = conn_to(ft)
    before = ft.http_requests
    c.executescript(dbmod.SCHEMA)
    assert ft.http_requests - before == 1                              # tutto lo schema in una richiesta
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"products", "stores", "evidence", "attempts", "site_profiles", "corrections", "index_queue"} <= names


def test_url_forms():
    for u in ("libsql://db-x.aws-eu-central-1.turso.io", "https://db-x.turso.io", "wss://db-x.turso.io", "db-x.turso.io/"):
        assert TursoConnection(u, "t")._endpoint.startswith("https://db-x") and TursoConnection(u, "t")._endpoint.endswith("/v2/pipeline")
    assert TursoConnection("libsql://a.turso.io", "t", pipeline="v3")._endpoint.endswith("/v3/pipeline")
    with pytest.raises(DatabaseError, match="PV_TURSO_URL"):
        TursoConnection("", "t")


def test_schema_is_created_once_per_process_not_per_request(ft):
    s = Settings(turso_url=ft.url, turso_token=ft.token)
    connect("x", s).close()
    n = ft.http_requests
    for _ in range(5):
        connect("x", s).close()
    assert ft.http_requests == n


def test_wrong_token_message_does_not_leak_the_token(ft):
    c = conn_to(ft, token="token-sbagliato-SEGRETO")
    with pytest.raises(DatabaseError) as e:
        c.execute("SELECT 1")
    assert "PV_TURSO_TOKEN" in str(e.value) and "SEGRETO" not in str(e.value) and "401" in str(e.value)


def test_sql_error_and_http_error_and_unreachable(ft):
    c = conn_to(ft)
    with pytest.raises(DatabaseError, match="errore SQL"):
        c.execute("SELECT * FROM tabella_che_non_esiste")
    ft.status = 503
    with pytest.raises(DatabaseError, match="503"):
        c.execute("SELECT 1")
    dead = TursoConnection("http://127.0.0.1:1", "t", timeout=2)
    with pytest.raises(DatabaseError, match="PV_TURSO_URL"):
        dead.execute("SELECT 1")


# ---------------------------------------------------------------- endpoint di diagnosi e 503
def make_client(settings):
    return TestClient(create_app(settings))


def test_diag_ok_reports_tables_without_secrets(ft):
    s = Settings(turso_url=ft.url, turso_token=ft.token, contact="me@example.org")
    j = make_client(s).get("/v1/diag").json()
    assert j["database"] == "ok" and j["database_modo"] == "turso" and "products" in j["tabelle"]
    assert j["turso_token_impostato"] is True and j["contatto_impostato"] is True
    assert ft.token not in str(j)


def test_diag_with_bad_token_explains_and_hides_the_token(ft):
    s = Settings(turso_url=ft.url, turso_token="token-sbagliato-SEGRETO")
    j = make_client(s).get("/v1/diag").json()
    assert j["database"] == "errore" and "PV_TURSO_TOKEN" in j["errore"] and "SEGRETO" not in str(j)


def test_diag_when_nothing_is_configured(tmp_path):
    j = make_client(Settings(db_path=str(tmp_path / "x.db"))).get("/v1/diag").json()
    assert j["database_modo"] == "sqlite-locale" and j["turso_url_impostato"] is False and j["database"] == "ok"
    assert j["contatto_impostato"] is False


def test_database_outage_is_503_with_a_reason_not_a_blind_500(ft):
    ft.status = 503
    c = make_client(Settings(turso_url=ft.url, turso_token=ft.token))
    dbmod._schema_ready.discard(ft.url)          # simula un riavvio: lo schema va ricreato e il DB non risponde
    r = c.get("/v1/coverage")
    assert r.status_code == 503 and "database non risponde" in r.json()["detail"]
    assert c.get("/v1/health").json() == {"ok": True}                    # la salute NON dipende dal database


def test_token_shape_describes_without_revealing():
    from server.diag import token_shape
    good = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9." + "a" * 120 + "." + "b" * 86
    g = token_shape(good)
    assert g["inizia_con_eyJ"] and len(g["lunghezze_delle_parti"]) == 3 and g["solo_caratteri_validi"]
    assert not g["contiene_spazi_o_virgolette"] and g["lunghezza_totale"] == len(good)
    bad = token_shape('"eyJabc.def\n')
    assert bad["contiene_spazi_o_virgolette"] and not bad["inizia_con_eyJ"] and len(bad["lunghezze_delle_parti"]) == 2
    assert token_shape("") is None and token_shape(None) is None
    assert good not in str(g) and "aaaa" not in str(g)


def test_diag_includes_token_shape_but_never_the_token(ft):
    s = Settings(turso_url=ft.url, turso_token=ft.token)
    j = make_client(s).get("/v1/diag").json()
    assert j["turso_token_forma"]["lunghezza_totale"] == len(ft.token) and ft.token not in str(j)
