"""Un finto Turso: parla il protocollo HTTP "Hrana" (/v2/pipeline) sopra SQLite in memoria.
Serve a provare che il client del servizio codifica e decodifica come il vero Turso.
NON prova le regole dell'account reale (quote, token scaduti): quelle si vedono solo su Turso."""
import base64
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": v}


def _dec(v):
    t = v["type"]
    return {"null": lambda: None, "integer": lambda: int(v["value"]), "float": lambda: float(v["value"]),
            "text": lambda: v["value"], "blob": lambda: base64.b64decode(v["base64"])}[t]()


class FakeTurso:
    def __init__(self, token="token-segreto-di-prova", status=None):
        self.token, self.status = token, status          # status: forza una risposta HTTP di errore
        self.db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        self.http_requests, self.statements, self.sql_log = 0, 0, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.http_requests += 1
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if outer.status:
                    return self._send(outer.status, {"error": "forzato dal test"})
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    return self._send(401, {"error": "The JWT is invalid"})
                if self.path not in ("/v2/pipeline", "/v3/pipeline"):
                    return self._send(404, {"error": "not found"})
                results = []
                for rq in json.loads(body)["requests"]:
                    if rq["type"] == "close":
                        results.append({"type": "ok", "response": {"type": "close"}})
                    elif rq["type"] == "execute":
                        results.append(outer._execute(rq["stmt"]))
                    else:
                        results.append({"type": "error", "error": {"message": "request non supportata"}})
                self._send(200, {"baton": None, "base_url": None, "results": results})

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def _execute(self, stmt):
        with self.lock:
            self.statements += 1
            self.sql_log.append(stmt["sql"])
            try:
                assert not stmt.get("named_args"), "il client deve mandare solo argomenti posizionali"
                cur = self.db.execute(stmt["sql"], [_dec(a) for a in stmt.get("args", [])])
                cols = [{"name": d[0], "decltype": None} for d in (cur.description or [])]
                rows = [[_enc(v) for v in r] for r in cur.fetchall()] if cur.description else []
                return {"type": "ok", "response": {"type": "execute", "result": {
                    "cols": cols, "rows": rows, "affected_row_count": max(cur.rowcount, 0),
                    "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None}}}
            except (sqlite3.Error, AssertionError) as e:
                return {"type": "error", "error": {"message": str(e), "code": "SQLITE_ERROR"}}

    def close(self):
        self.srv.shutdown()
