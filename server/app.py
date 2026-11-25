import sys
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from probe.probe import Robots

from . import catalogs, products, stores
from .config import Settings
from .db import DatabaseError, connect
from .scan import run_scan


class CorrectionIn(BaseModel):
    code: str
    field: str
    value: str
    user_id: str


def create_app(settings: Settings | None = None, fetcher=None) -> FastAPI:
    settings = settings or Settings()
    fetcher = fetcher or products.make_fetcher(settings)
    robots = Robots(fetcher)
    app = FastAPI(title="Prezzi Vicini", version="1.0")

    @app.exception_handler(DatabaseError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": f"Il database non risponde: {exc}"})

    @app.get("/v1/health")
    def health():
        return {"ok": True}

    @app.get("/v1/scan")
    def scan(code: str, lat: float | None = Query(None, ge=-90, le=90), lon: float | None = Query(None, ge=-180, le=180),
             radius_km: float | None = None):
        conn = connect(settings.db_path, settings)
        try:
            return run_scan(conn, code, lat, lon, radius_km, settings, fetcher, robots)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            conn.close()

    @app.post("/v1/corrections")
    def correction(c: CorrectionIn):
        conn = connect(settings.db_path, settings)
        try:
            out = products.add_correction(conn, c.code, c.field, c.value, c.user_id)
            return {"ok": True, "saved": out, "note": f"La correzione si applica quando {settings.correction_min_users} "
                    "utenti diversi propongono lo stesso valore."}
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            conn.close()

    @app.get("/v1/coverage")
    def coverage():
        conn = connect(settings.db_path, settings)
        try:
            return {"cataloghi": catalogs.coverage(conn), "negozi": stores.count_stores(conn)}
        finally:
            conn.close()

    @app.get("/v1/diag")
    def diag():
        """Stato del servizio in chiaro, senza segreti: serve a capire perché qualcosa non funziona."""
        host = urlparse(settings.turso_url.replace("libsql://", "https://")).hostname if settings.turso_url else None
        info = {"python": sys.version.split()[0], "database_modo": "turso" if settings.use_turso else "sqlite-locale",
                "turso_url_impostato": bool(settings.turso_url), "turso_token_impostato": bool(settings.turso_token),
                "turso_host": host, "contatto_impostato": settings.contact != "contatto-non-configurato",
                "budget_verifica_s": settings.index_budget_s}
        try:
            conn = connect(settings.db_path, settings)
            try:
                conn.execute("SELECT 1").fetchone()
                info["database"] = "ok"
                info["tabelle"] = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            finally:
                conn.close()
        except Exception as e:
            msg = str(e)
            for secret in (settings.turso_token,):
                if secret:
                    msg = msg.replace(secret, "***")
            info["database"] = "errore"
            info["errore"] = f"{type(e).__name__}: {msg}"[:400]
        return info

    return app
