"""Connessione al database: SQLite locale o Turso (libSQL remoto)."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  gtin TEXT PRIMARY KEY, found INTEGER NOT NULL, name TEXT, brand TEXT, quantity TEXT,
  image_url TEXT, source TEXT, fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stores(
  osm_type TEXT NOT NULL, osm_id INTEGER NOT NULL, name TEXT, brand TEXT, wikidata TEXT, chain TEXT,
  shop TEXT, lat REAL NOT NULL, lon REAL NOT NULL, address TEXT, opening_hours TEXT,
  PRIMARY KEY(osm_type, osm_id));
CREATE INDEX IF NOT EXISTS stores_lat ON stores(lat);
CREATE INDEX IF NOT EXISTS stores_chain ON stores(chain);
CREATE TABLE IF NOT EXISTS evidence(
  gtin TEXT NOT NULL, chain TEXT NOT NULL, level INTEGER NOT NULL, url TEXT NOT NULL, title TEXT,
  price REAL, currency TEXT, verified_at TEXT NOT NULL, PRIMARY KEY(gtin, chain, url));
CREATE TABLE IF NOT EXISTS attempts(
  gtin TEXT NOT NULL, chain TEXT NOT NULL, outcome TEXT NOT NULL, tried_at TEXT NOT NULL,
  PRIMARY KEY(gtin, chain));
CREATE TABLE IF NOT EXISTS site_profiles(
  chain TEXT NOT NULL, base TEXT NOT NULL, status TEXT NOT NULL, search_url TEXT, search_param TEXT,
  hidden TEXT, checked_at TEXT NOT NULL, note TEXT, PRIMARY KEY(chain, base));
CREATE TABLE IF NOT EXISTS corrections(
  id INTEGER PRIMARY KEY AUTOINCREMENT, gtin TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL,
  user_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS index_queue(gtin TEXT PRIMARY KEY, requested_at TEXT NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def older_than(iso: str, days: float) -> bool:
    t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - t > timedelta(days=days)


# --- libSQL (Turso) support --------------------------------------------------
try:
    from libsql_client import create_client_sync
    LIBSQL_AVAILABLE = True
except ImportError:  # pragma: no cover - dipende dall'ambiente di deploy
    LIBSQL_AVAILABLE = False


class _TursoRow:
    """Riga compatibile con sqlite3.Row: accesso per nome (row["gtin"]) e per indice (row[0])."""

    def __init__(self, columns, values):
        self._columns = list(columns or [])
        self._values = list(values or [])
        self._by_name = dict(zip(self._columns, self._values)) if self._columns else {}

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._by_name[key]
        return self._values[key]

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._columns


class _TursoCursor:
    """Wrapper sui risultati di libsql_client per mimare sqlite3.Cursor."""

    def __init__(self, columns, rows):
        self._columns = list(columns or [])
        self._rows = list(rows or [])
        self._index = 0

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = _TursoRow(self._columns, self._rows[self._index])
        self._index += 1
        return row

    def fetchall(self):
        out = [_TursoRow(self._columns, r) for r in self._rows[self._index:]]
        self._index = len(self._rows)
        return out

    @property
    def rowcount(self):
        return len(self._rows)


class _TursoConnection:
    """Wrapper minimale compatibile con sqlite3.Connection sopra libsql_client sync."""

    def __init__(self, url: str, token: str):
        self._client = create_client_sync(url=url, auth_token=token)
        self.row_factory = None
        self.executescript(SCHEMA)

    def execute(self, sql, params=()):
        result = self._client.execute(sql, list(params))
        return _TursoCursor(getattr(result, "columns", None), getattr(result, "rows", []))

    def executemany(self, sql, params_list):
        for params in params_list or []:
            self._client.execute(sql, list(params))

    def executescript(self, sql_script):
        for statement in sql_script.split(";"):
            statement = statement.strip()
            if statement:
                self._client.execute(statement)

    def commit(self):
        pass  # libsql_client auto-committa ogni statement

    def close(self):
        self._client.close()


def connect(path: str, settings=None):
    """Apri una connessione al database.

    Se ``settings.use_turso`` è True e ``libsql-client`` è disponibile, ci si connette
    a Turso (DB remoto, mai sul PC). Altrimenti si usa SQLite locale (solo dev/test).
    """
    if settings is not None and getattr(settings, "use_turso", False) and LIBSQL_AVAILABLE:
        return _TursoConnection(settings.turso_url, settings.turso_token)

    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    if path != ":memory:":
        c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


@contextmanager
def session(path: str, settings=None):
    c = connect(path, settings)
    try:
        yield c
        c.commit()
    finally:
        c.close()