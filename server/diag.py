"""Diagnosi del servizio in chiaro, senza mai mostrare segreti. Usata da /v1/diag e da `cli diag`."""
import sys
from urllib.parse import urlparse

from .db import connect


def diagnose(settings) -> dict:
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
            info["conteggi"] = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                for t in ("stores", "site_profiles", "products", "evidence", "index_queue")
                                if t in info["tabelle"]}
        finally:
            conn.close()
    except Exception as e:
        msg = str(e)
        for secret in (settings.turso_token,):
            if secret:
                msg = msg.replace(secret, "***")
        info["database"] = "errore"
        info["errore"] = f"{type(e).__name__}: {msg}"[:500]
    return info
