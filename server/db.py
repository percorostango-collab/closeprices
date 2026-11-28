"""Connessione al database: SQLite locale (sviluppo/test) o Turso (libSQL remoto, produzione).

Turso si parla via HTTPS con il protocollo "Hrana over HTTP" (/v2/pipeline), usando solo `requests`:
nessuna libreria nativa, nessun WebSocket, stesso comportamento su Windows, Linux, Render e GitHub Actions."""
import base64
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

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
CREATE TABLE IF NOT EXISTS offers(
  gtin TEXT NOT NULL, store TEXT NOT NULL, url TEXT NOT NULL, title TEXT, price REAL NOT NULL, currency TEXT,
  match TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(gtin, store, url));
CREATE TABLE IF NOT EXISTS offer_queries(
  gtin TEXT NOT NULL, source TEXT NOT NULL, n_offers INTEGER NOT NULL, name_hint TEXT, fetched_at TEXT NOT NULL,
  PRIMARY KEY(gtin, source));
CREATE TABLE IF NOT EXISTS discovery_runs(
  gtin TEXT PRIMARY KEY, state TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
  n_candidates INTEGER DEFAULT 0, n_verified INTEGER DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS api_usage(source TEXT NOT NULL, month TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(source, month));
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def older_than(iso: str, days: float) -> bool:
    t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - t > timedelta(days=days)


def clean_token(tok) -> str:
    """Ripulisce un token incollato male: virgolette, spazi, a capo, "Bearer " e qualsiasi cosa stia PRIMA dell'inizio
    del JWT. Un token Turso è un JWT e comincia sempre con 'eyJ'."""
    t = re.sub(r"\s+", "", str(tok or ""))
    t = re.sub(r"^(?:authorization:)?bearer", "", t.strip("\"'`"), flags=re.I)
    t = t.strip("\"'`")
    i = t.find("eyJ")
    return t[i:] if i > 0 else t


class DatabaseError(Exception):
    """Il database non risponde o ha rifiutato una richiesta. Il messaggio non contiene mai il token."""


# ---------------------------------------------------------------------------- protocollo Hrana/HTTP
def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _dec(v):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v.get("base64", ""))
    return v.get("value")


_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def _positional(sql, params):
    """Accetta i parametri come sqlite3: lista/tupla per i '?', dizionario per i ':nome'.
    I nomi si trasformano in '?' prima dell'invio, così non dipendiamo da come il server li interpreta."""
    if isinstance(params, dict):
        names = _NAMED.findall(sql)
        return _NAMED.sub("?", sql), [params[n] for n in names]
    return sql, list(params or [])


class Row:
    """Come sqlite3.Row: accesso per nome o per posizione, keys(), dict(riga)."""
    __slots__ = ("_k", "_v")

    def __init__(self, keys, values):
        self._k, self._v = keys, values

    def __getitem__(self, i):
        if isinstance(i, str):
            try:
                return self._v[self._k.index(i)]
            except ValueError:
                raise IndexError(f"No item with that key: {i}") from None
        return self._v[i]

    def keys(self):
        return list(self._k)

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def __repr__(self):
        return f"Row({dict(zip(self._k, self._v))})"


class _Cursor:
    def __init__(self, cols, rows, rowcount=-1, lastrowid=None):
        self.description = [(c,) + (None,) * 6 for c in cols]
        self._rows = [Row(cols, r) for r in rows]
        self._i = 0
        self.rowcount, self.lastrowid = rowcount, lastrowid

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        out, self._i = self._rows[self._i:], len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


class TursoConnection:
    """Compatibile con la parte di sqlite3.Connection che usa il servizio. Ogni istruzione è confermata subito
    (autocommit): executemany manda i comandi a gruppi in una sola richiesta di rete."""
    CHUNK = 200

    def __init__(self, url, token, timeout=30, pipeline="v2", session=None):
        if not url or not token:
            raise DatabaseError("Turso non configurato: mancano PV_TURSO_URL e/o PV_TURSO_TOKEN.")
        base = re.sub(r"^(libsql|wss?)://", "https://", url.strip()).rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        self._endpoint = f"{base}/{pipeline}/pipeline"
        self._token, self._timeout = clean_token(token), timeout
        self._s = session or requests.Session()
        self.row_factory = None

    def _post(self, statements):
        reqs = [{"type": "execute", "stmt": {"sql": q, "args": [_enc(a) for a in args], "want_rows": True}}
                for q, args in statements]
        try:
            r = self._s.post(self._endpoint, json={"baton": None, "requests": reqs + [{"type": "close"}]},
                             headers={"Authorization": f"Bearer {self._token}"}, timeout=self._timeout)
        except requests.RequestException as e:
            raise DatabaseError(f"connessione a Turso non riuscita ({type(e).__name__}): controlla PV_TURSO_URL") from None
        if r.status_code in (401, 403):
            raise DatabaseError(f"Turso ha rifiutato il token (HTTP {r.status_code}): controlla PV_TURSO_TOKEN")
        if r.status_code != 200:
            raise DatabaseError(f"Turso ha risposto HTTP {r.status_code} su {self._endpoint.split('/', 3)[2]}: "
                                f"{r.text[:200].replace(self._token, '***')}")
        try:
            results = r.json()["results"]
        except (ValueError, KeyError):
            raise DatabaseError("risposta di Turso non valida") from None
        out = []
        for res in results[:len(reqs)]:
            if res.get("type") == "error":
                msg = (res.get("error") or {}).get("message", "errore sconosciuto")
                raise DatabaseError(f"errore SQL da Turso: {msg}"[:300].replace(self._token, "***"))
            out.append(res["response"]["result"])
        return out

    @staticmethod
    def _cursor(res):
        cols = [c.get("name") for c in res.get("cols", [])]
        rows = [[_dec(v) for v in row] for row in res.get("rows", [])]
        lri = res.get("last_insert_rowid")
        return _Cursor(cols, rows, res.get("affected_row_count", -1), int(lri) if lri is not None else None)

    def execute(self, sql, params=()):
        q, args = _positional(sql, params)
        return self._cursor(self._post([(q, args)])[0])

    def executemany(self, sql, seq):
        batch = [_positional(sql, p) for p in seq or []]
        for i in range(0, len(batch), self.CHUNK):
            self._post(batch[i:i + self.CHUNK])

    def executescript(self, script):
        stmts = [(s.strip(), []) for s in script.split(";") if s.strip()]
        if stmts:
            self._post(stmts)

    def commit(self):
        pass

    def close(self):
        self._s.close()


_schema_ready = set()
_schema_lock = threading.Lock()


def connect(path: str, settings=None):
    """Turso se `settings` ha URL e token, altrimenti SQLite locale (sviluppo e test).
    Lo schema su Turso si crea una volta per processo, non a ogni richiesta."""
    if settings is not None and getattr(settings, "use_turso", False):
        c = TursoConnection(settings.turso_url, settings.turso_token, pipeline=getattr(settings, "turso_pipeline", "v2"))
        key = settings.turso_url
        if key not in _schema_ready:
            with _schema_lock:
                if key not in _schema_ready:
                    c.executescript(SCHEMA)
                    _schema_ready.add(key)
        return c
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
